"""`ZapAdapter` — parses OWASP ZAP baseline-scan JSON reports into
`Finding`s (dast-scanner PR5a, design D2/D5, tasks 5.10).

Implements `ScannerAdapterPort` (Module 7 D1), mirroring
`SemgrepAdapter`/`PipAuditAdapter`'s shape (`parse()`/`supports()`). Unlike
those adapters, the `RunResult` passed here is NOT ZAP's own baseline-run
stdout — it is the stdout of a SECOND, report-reading run (`cat
report.json`) against the same named volume (design D7's two-run split),
produced by `infrastructure.container.zap_dast_execution
.ZapDastDockerExecution` (dast-scanner PR5b, not yet built — PR5a is pure
parsing only).

## Exit-code-agnostic parse (design D5/D2 precedent: Semgrep D6, pip-audit D4)
ZAP's own process exit code is noisy/non-standard (`zap-baseline.py`
returns non-zero for WARN-level findings unless `-I` is passed, plus other
undocumented edge cases) — `parse()` never branches on `result.exit_code`.
Only `result.timed_out` and the JSON shape gate success/failure.

## `site`-less JSON is a genuine failure, not zero-alerts
A ZAP baseline report always has a top-level `site` key, even for a clean
scan with zero alerts (`{"site": []}` or `{"site": [{"alerts": []}]}` — both
valid, both return `[]`). JSON missing the `site` key entirely, JSON that
fails to parse at all, or an empty stdout string is NOT a recognizable ZAP
report and raises `ZapFailedError` — mirroring exactly how
`semgrep_adapter._parse_json_report`/`pip_audit_adapter._parse_json_report`
treat their own missing-key case as a genuine tool failure, never a
silently empty scan.

## Per-(alert, instance) findings, capped
One `Finding` per `(alert, instance)` pair — matching Semgrep's
per-match/per-instance granularity precedent — capped at
`_MAX_INSTANCES_PER_ALERT` per alert to bound row count on a single
high-volume alert (e.g. a CSRF alert firing on hundreds of URLs). A
judgement call per the design's Open Questions, to be revisited against a
real ZAP report in a later PR.

## Fingerprint excludes the query string (deliberate, security-relevant)
`fingerprint = sha256(f"{pluginid}:{method}:{uri_without_query}")` — the
query string is stripped via `urllib.parse.urlsplit` before hashing, so a
session-token-bearing query parameter can neither destabilize dedup (two
scans of the same endpoint under different session tokens must dedup to
the SAME row) nor leak into a supposedly-stable key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

#: Bounds the number of `Finding`s produced for a single alert that fires on
#: many URLs — design Interfaces section / Open Questions (judgement call,
#: not a measurement).
_MAX_INSTANCES_PER_ALERT = 25

#: ZAP's `riskcode` -> `FindingSeverity` (design Interfaces section). ZAP has
#: no CRITICAL rung. Any value outside this map falls back to
#: `_UNKNOWN_SEVERITY_FALLBACK` (AST-SAST D3 / Semgrep D7 precedent).
_SEVERITY_MAP: dict[str, FindingSeverity] = {
    "3": FindingSeverity.HIGH,
    "2": FindingSeverity.MEDIUM,
    "1": FindingSeverity.LOW,
    "0": FindingSeverity.INFO,
}
_UNKNOWN_SEVERITY_FALLBACK = FindingSeverity.MEDIUM


class ZapFailedError(Exception):
    """A genuine adapter/tool failure — never raised for "zero alerts"."""


class ZapAdapter(ScannerAdapterPort):
    """Parses a ZAP baseline-scan JSON report into `Finding`s.

    Implements `ScannerAdapterPort` (Module 7 D1) — driven via
    `infrastructure.container.zap_dast_execution.ZapDastDockerExecution`
    (dast-scanner PR5b), which reads `report.json` off the scan volume and
    passes the resulting `RunResult` here.
    """

    def __init__(self, runner: ContainerRunnerPort, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    def parse(
        self,
        result: RunResult,
        scan_task_id: uuid.UUID,
    ) -> list[Finding]:
        """Interpret one ZAP baseline `RunResult`.

        Zero alerts on a clean scan is a valid, successful outcome — returns
        `[]`, not an error.
        """
        if result.timed_out:
            raise ZapFailedError(
                f"zap-baseline scan timed out (exit_code={result.exit_code}, "
                f"stderr={result.stderr!r})"
            )

        report = _parse_json_report(result.stdout, result.stderr)
        now = datetime.now(UTC).replace(tzinfo=None)
        findings: list[Finding] = []
        for site in report.get("site") or []:
            for alert in site.get("alerts") or []:
                findings.extend(_alert_to_findings(alert, scan_task_id, now))
        return findings

    def supports(self, scanner_type: ScannerType) -> bool:
        """`ZapAdapter` only handles `ScannerType.DAST`."""
        return scanner_type == ScannerType.DAST


def _parse_json_report(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse `stdout` as a ZAP baseline JSON report.

    Mirrors `semgrep_adapter._parse_json_report`/
    `pip_audit_adapter._parse_json_report`: empty stdout, malformed JSON, or
    JSON missing the report's own top-level key (`site`, here) is a genuine
    tool failure — never a silently empty scan. A present-but-empty `site`
    list (or an alert-less site) is the valid "zero alerts" outcome, handled
    by the caller, not here.
    """
    stripped = stdout.strip()
    if not stripped:
        raise ZapFailedError(f"empty zap-baseline output (stderr={stderr!r})")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ZapFailedError(f"malformed zap-baseline JSON report: {exc}") from exc
    if not isinstance(parsed, dict) or "site" not in parsed:
        raise ZapFailedError(
            f"malformed zap-baseline JSON report: missing 'site' key (stderr={stderr!r})"
        )
    return parsed


def _alert_to_findings(
    alert: dict[str, Any],
    scan_task_id: uuid.UUID,
    now: datetime,
) -> list[Finding]:
    pluginid = alert.get("pluginid") or "unknown-plugin"
    title = alert.get("alert") or "unknown-alert"
    severity = _map_severity(alert.get("riskcode"))
    instances = (alert.get("instances") or [])[:_MAX_INSTANCES_PER_ALERT]

    return [
        _instance_to_finding(alert, instance, pluginid, title, severity, scan_task_id, now)
        for instance in instances
    ]


def _instance_to_finding(
    alert: dict[str, Any],
    instance: dict[str, Any],
    pluginid: str,
    title: str,
    severity: FindingSeverity,
    scan_task_id: uuid.UUID,
    now: datetime,
) -> Finding:
    uri = instance.get("uri") or ""
    method = instance.get("method") or ""
    param = instance.get("param") or ""
    evidence = instance.get("evidence") or ""
    query = urlsplit(uri).query

    return Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=severity,
        rule_id=pluginid,
        title=title,
        fingerprint=_fingerprint(pluginid, method, uri),
        created_at=now,
        updated_at=now,
        file_path=None,
        line_number=None,
        raw_evidence={
            "uri": uri,
            "query": query,
            "method": method,
            "param": param,
            "evidence": evidence,
            "cweid": alert.get("cweid"),
            "wascid": alert.get("wascid"),
            "confidence": alert.get("confidence"),
            "solution": alert.get("solution"),
            "alert_ref": alert.get("alert_ref"),
        },
        snippet=evidence,
    )


def _map_severity(riskcode: str | None) -> FindingSeverity:
    """Translate ZAP's `riskcode` (design Interfaces section); any value
    outside `_SEVERITY_MAP` falls back to MEDIUM + a logged warning rather
    than failing the whole scan."""
    severity = _SEVERITY_MAP.get(riskcode or "")
    if severity is None:
        logger.warning(
            "zap-baseline reported an unrecognized riskcode %r — falling back to MEDIUM",
            riskcode,
        )
        return _UNKNOWN_SEVERITY_FALLBACK
    return severity


def _fingerprint(pluginid: str, method: str, uri: str) -> str:
    """Deterministic dedup hash — same convention as
    `semgrep_adapter._fingerprint`/`pip_audit_adapter._fingerprint`: sha256
    hex digest over the fields that identify a distinct violation instance.

    The query string is deliberately excluded (stripped via `urlsplit`)
    before hashing, so a session-token-bearing query param can neither
    destabilize dedup nor leak into a supposedly-stable key."""
    uri_without_query = urlsplit(uri)._replace(query="", fragment="").geturl()
    canonical = f"{pluginid}:{method}:{uri_without_query}"
    return hashlib.sha256(canonical.encode()).hexdigest()
