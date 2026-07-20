"""`AstSastAdapter` — runs the external `sast-scanner` AST-based Python SAST
tool against a checked-out volume and parses its JSON report into
`Finding`s (Module 11 PR1, tasks 2.1-2.5).

Implements `ScannerAdapterPort` (Module 7 D1), mirroring
`GitleaksAdapter`/`PipAuditAdapter`'s shape (`scan()`/`parse()`/`supports()`),
selected via `infrastructure.scanners.registry.get_adapter(ScannerType.SAST, ...)`.

## Non-JSON-prefixed stdout (D2)
`sast-scanner`'s `--format json` CLI still prints two preamble lines
(`Analizando: ...` / `Hallazgos: ...`) to stdout BEFORE the JSON report
(confirmed against the real, `v1.0.0`-tagged `sast/cli.py`) — unlike
`GitleaksAdapter`/`PipAuditAdapter`, `parse()` cannot assume stdout is pure
JSON. It slices from the first `{` character instead. No `{` present, or
malformed JSON after slicing, or `result.timed_out=True` -> `SastFailedError`
(deterministic; the tool genuinely crashed/produced nothing on stdout — not
"zero findings").

## Per-finding severity (D3)
Unlike Gitleaks/pip-audit's single fixed `DEFAULT_SEVERITY` constant,
`sast-scanner` reports its OWN severity per finding, in Spanish
(`ALTA`/`MEDIA`/`BAJA`). `_SEVERITY_MAP` translates it; any value outside the
map falls back to `FindingSeverity.MEDIUM` with a logged warning rather than
failing the whole scan — a new upstream severity value must never sink an
otherwise-successful report.

## Path normalization (D4)
`sast-scanner` reports `file` as the absolute path under its `--path` mount
target (`/checkout/checkout/...`). No reusable path-normalization helper
exists elsewhere in this codebase (`GitleaksAdapter` stores its raw
`entry["File"]`; `PipAuditAdapter` uses a hardcoded `requirements.txt`
literal) — this adapter strips its own prefix via `str.removeprefix`,
matching the shared CONVENTION (`Finding.file_path` stored repo-relative)
without reusing code that does not exist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

_MOUNT_PATH = "/checkout"
#: `GitCheckout` clones into a `checkout/` subdir of the SHARED volume root
#: (its own mount path is `/workspace`, so on-disk that subdir is
#: `/workspace/checkout`); mounted here at `/checkout` instead, the same
#: files resolve at `/checkout/checkout` (same convention as
#: `gitleaks_adapter._TARGET_DIR`/`pip_audit_adapter._TARGET_REQUIREMENTS`).
_TARGET_DIR = "/checkout/checkout"

#: Fixed argv-only command — never interpolated from repo content (threat
#: matrix: command composition, task 2.5).
_SAST_ARGV: tuple[str, ...] = (
    "python",
    "-m",
    "sast.cli",
    "--path",
    _TARGET_DIR,
    "--format",
    "json",
)

#: `sast-scanner` reports severity in Spanish (D3) — translated here. Any
#: value outside this map falls back to `_UNKNOWN_SEVERITY_FALLBACK`.
_SEVERITY_MAP: dict[str, FindingSeverity] = {
    "ALTA": FindingSeverity.HIGH,
    "MEDIA": FindingSeverity.MEDIUM,
    "BAJA": FindingSeverity.LOW,
}
_UNKNOWN_SEVERITY_FALLBACK = FindingSeverity.MEDIUM


class SastFailedError(Exception):
    """A genuine adapter/tool failure — never raised for "zero findings" (D2)."""


class AstSastAdapter(ScannerAdapterPort):
    """Launches the pinned `sast-scanner` image against a checked-out volume.

    Implements `ScannerAdapterPort` (Module 7 D1) — selected via
    `infrastructure.scanners.registry.get_adapter(ScannerType.SAST, ...)`.
    """

    def __init__(self, runner: ContainerRunnerPort, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    def scan(self, volume_name: str) -> RunResult:
        """Run `sast-scanner` read-only, network-disabled, against `volume_name`.

        Returns the raw `RunResult` — callers pass it to `parse()` to get
        `Finding`s (kept separate so `parse()` stays a pure, easily
        triangulated method with no container dependency). `network_disabled
        =True` is safe (D6): the `sast-scanner` source is fetched at
        IMAGE-BUILD time only, and the running scan is pure `ast`-based
        static analysis with zero runtime egress. No `tmp_exec` needed
        either — no subprocess/venv bootstrapping, unlike pip-audit.
        """
        return self._runner.run(
            image=self._settings.scan_sast_image,
            command=list(_SAST_ARGV),
            volume_name=volume_name,
            mount_path=_MOUNT_PATH,
            read_only_mount=True,
            network_disabled=True,
            limits=self._resource_limits(),
            timeout_seconds=self._settings.scan_timeout_seconds,
        )

    def parse(
        self,
        result: RunResult,
        scan_task_id: uuid.UUID,
    ) -> list[Finding]:
        """Interpret one `sast-scanner` `RunResult` per the D2 slice-from-`{`
        contract.

        Zero findings on a clean scan (or a repo with no Python source, or
        Python source that triggers no rule) is a valid, successful
        outcome — returns `[]`, not an error.
        """
        if result.timed_out:
            raise SastFailedError(
                f"sast-scanner timed out (exit_code={result.exit_code}, stderr={result.stderr!r})"
            )

        report = _parse_json_report(result.stdout, result.stderr)
        now = datetime.now(UTC).replace(tzinfo=None)
        return [
            _violation_to_finding(entry, scan_task_id, now) for entry in report.get("findings", [])
        ]

    def supports(self, scanner_type: ScannerType) -> bool:
        """`AstSastAdapter` only handles `ScannerType.SAST`."""
        return scanner_type == ScannerType.SAST

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )


def _parse_json_report(stdout: str, stderr: str) -> dict[str, Any]:
    """Slice `stdout` from its first `{` before parsing (D2) — `sast-scanner`
    prints two non-JSON preamble lines ahead of the JSON report."""
    try:
        start = stdout.index("{")
    except ValueError as exc:
        raise SastFailedError(
            f"no JSON object found in sast-scanner output (stderr={stderr!r})"
        ) from exc
    try:
        parsed = json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise SastFailedError(f"malformed sast-scanner JSON report: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SastFailedError(
            f"malformed sast-scanner JSON report: expected an object, got {type(parsed).__name__}"
        )
    return parsed


def _violation_to_finding(
    entry: dict[str, Any],
    scan_task_id: uuid.UUID,
    now: datetime,
) -> Finding:
    rule_id = entry.get("rule_id") or "unknown-rule"
    title = entry.get("title") or rule_id
    line_number = entry.get("line")
    file_path = _normalize_path(entry.get("file") or "")
    description = entry.get("description") or ""
    remediation = entry.get("remediation") or ""
    severity = _map_severity(entry.get("severity"))

    return Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=severity,
        rule_id=rule_id,
        title=title,
        fingerprint=_fingerprint(rule_id, file_path, line_number),
        created_at=now,
        updated_at=now,
        file_path=file_path,
        line_number=line_number,
        raw_evidence={"description": description, "remediation": remediation},
        snippet=description,
    )


def _map_severity(raw_severity: str | None) -> FindingSeverity:
    """Translate `sast-scanner`'s Spanish severity (D3); any value outside
    `_SEVERITY_MAP` falls back to MEDIUM + a logged warning rather than
    failing the whole scan."""
    severity = _SEVERITY_MAP.get(raw_severity or "")
    if severity is None:
        logger.warning(
            "sast-scanner reported an unrecognized severity %r — falling back to MEDIUM",
            raw_severity,
        )
        return _UNKNOWN_SEVERITY_FALLBACK
    return severity


def _normalize_path(file_path: str) -> str:
    """Strip the container mount-path prefix (D4) so `Finding.file_path`
    never leaks the container's internal mount layout."""
    return file_path.removeprefix(f"{_TARGET_DIR}/")


def _fingerprint(rule_id: str, file_path: str, line_number: int | None) -> str:
    """Deterministic dedup hash — same convention as
    `gitleaks_adapter._fingerprint`/`pip_audit_adapter._fingerprint`: sha256
    hex digest over the fields that identify a distinct violation instance."""
    canonical = f"{rule_id}:{file_path}:{line_number}"
    return hashlib.sha256(canonical.encode()).hexdigest()
