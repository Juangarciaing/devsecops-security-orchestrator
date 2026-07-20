"""`SemgrepAdapter` — runs the pinned `semgrep-scanner` image against a
checked-out volume and parses its JSON output into `Finding`s (Module 11
PR2, tasks 3.1-3.7).

Implements `ScannerAdapterPort` (Module 7 D1), mirroring
`AstSastAdapter`/`PipAuditAdapter`'s shape (`scan()`/`parse()`/`supports()`),
selected via
`infrastructure.scanners.registry.get_adapter(ScannerType.SEMGREP, ...)`.

## Pure-JSON stdout, exit-code-agnostic parse (D6)
Confirmed against the real, installed `semgrep==1.170.0` CLI
(`semgrep scan --help` and a live scan against a small fixture, including
under the exact hardened-container conditions `DockerContainerRunner` uses
— non-root, read-only rootfs, `cap_drop=ALL`, `--network none`, `/tmp`
`noexec` tmpfs): `--quiet --json` emits PURE JSON on stdout with no
preamble line (unlike `sast-scanner`) — `parse()` uses
`json.loads(stdout.strip())` (pip-audit style), NOT AST-SAST's
slice-from-`{`. Semgrep's own exit code is IGNORED: confirmed exit 0 even
WITH findings present in a real run (Semgrep only reports non-zero for its
own opt-in `--error` flag or a genuine execution/config error) — `parse()`
is driven entirely by JSON `results[]` presence, mirroring pip-audit's D4
parse-driven contract. Empty stdout, malformed JSON, or a missing `results`
key -> `SemgrepFailedError` (deterministic) — never a silently empty scan.

## Per-finding severity map + MEDIUM fallback (D7, AST-SAST D3 precedent)
Confirmed real `extra.severity` values are `ERROR`/`WARNING`/`INFO`
(uppercase) via a live scan against a real vulnerable fixture.
`_SEVERITY_MAP` translates to HIGH/MEDIUM/LOW; any other value falls back
to `FindingSeverity.MEDIUM` with a logged warning rather than failing the
whole scan.

## Path normalization (D9)
Confirmed via a live scan with an ABSOLUTE scan-target argument: Semgrep
returns `path` as the absolute, mount-prefixed path
(`/checkout/checkout/...`) — the same convention as `sast-scanner`
(`ast_sast_adapter._normalize_path`). `_normalize_path` strips that prefix
so `Finding.file_path` never leaks the container's internal mount layout.
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
#: `ast_sast_adapter._TARGET_DIR`/`pip_audit_adapter._TARGET_REQUIREMENTS`).
_TARGET_DIR = "/checkout/checkout"

#: Fixed argv-only command — never interpolated from repo content (threat
#: matrix: command composition, task 3.5). Rules are baked into `/rules` at
#: BUILD time (`docker/semgrep.Dockerfile`); `--metrics=off
#: --disable-version-check` are belt-and-suspenders zero-egress (the running
#: container also launches with `network_disabled=True`, D3).
_SEMGREP_ARGV: tuple[str, ...] = (
    "semgrep",
    "scan",
    "--config",
    "/rules",
    "--json",
    "--quiet",
    "--metrics=off",
    "--disable-version-check",
    _TARGET_DIR,
)

#: Confirmed real `extra.severity` values (D7, live-verified) — translated
#: here. Any value outside this map falls back to
#: `_UNKNOWN_SEVERITY_FALLBACK`.
_SEVERITY_MAP: dict[str, FindingSeverity] = {
    "ERROR": FindingSeverity.HIGH,
    "WARNING": FindingSeverity.MEDIUM,
    "INFO": FindingSeverity.LOW,
}
_UNKNOWN_SEVERITY_FALLBACK = FindingSeverity.MEDIUM


class SemgrepFailedError(Exception):
    """A genuine adapter/tool failure — never raised for "zero findings" (D6)."""


class SemgrepAdapter(ScannerAdapterPort):
    """Launches the pinned `semgrep-scanner` image against a checked-out volume.

    Implements `ScannerAdapterPort` (Module 7 D1) — selected via
    `infrastructure.scanners.registry.get_adapter(ScannerType.SEMGREP, ...)`.
    """

    def __init__(self, runner: ContainerRunnerPort, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    def scan(self, volume_name: str) -> RunResult:
        """Run `semgrep` read-only, network-disabled, against `volume_name`.

        Returns the raw `RunResult` — callers pass it to `parse()` to get
        `Finding`s (kept separate so `parse()` stays a pure, easily
        triangulated method with no container dependency). `network_disabled
        =True` is safe (D3): rules are baked into the image at BUILD time
        only, and the running scan makes zero runtime network attempts
        (`--metrics=off --disable-version-check` plus the image's own
        `SEMGREP_SEND_METRICS=off`). No `tmp_exec` needed either — confirmed
        via a live hardened-container smoke test: semgrep needs no
        subprocess/venv bootstrapping under `/tmp`, unlike pip-audit.
        """
        return self._runner.run(
            image=self._settings.scan_semgrep_image,
            command=list(_SEMGREP_ARGV),
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
        """Interpret one `semgrep` `RunResult` per the D6 pure-JSON,
        parse-driven contract.

        Zero findings on a clean scan (or a repo with no rule matches) is a
        valid, successful outcome — returns `[]`, not an error.
        """
        if result.timed_out:
            raise SemgrepFailedError(
                f"semgrep timed out (exit_code={result.exit_code}, stderr={result.stderr!r})"
            )

        report = _parse_json_report(result.stdout, result.stderr)
        now = datetime.now(UTC).replace(tzinfo=None)
        return [_result_to_finding(entry, scan_task_id, now) for entry in report.get("results", [])]

    def supports(self, scanner_type: ScannerType) -> bool:
        """`SemgrepAdapter` only handles `ScannerType.SEMGREP`."""
        return scanner_type == ScannerType.SEMGREP

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )


def _parse_json_report(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse `stdout` as pure JSON (D6) — confirmed `--quiet --json` never
    prints any preamble, unlike `sast-scanner`."""
    stripped = stdout.strip()
    if not stripped:
        raise SemgrepFailedError(f"empty semgrep output (stderr={stderr!r})")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SemgrepFailedError(f"malformed semgrep JSON report: {exc}") from exc
    if not isinstance(parsed, dict) or "results" not in parsed:
        raise SemgrepFailedError(
            f"malformed semgrep JSON report: missing 'results' key (stderr={stderr!r})"
        )
    return parsed


def _result_to_finding(
    entry: dict[str, Any],
    scan_task_id: uuid.UUID,
    now: datetime,
) -> Finding:
    check_id = entry.get("check_id") or "unknown-rule"
    file_path = _normalize_path(entry.get("path") or "")
    start = entry.get("start") or {}
    line_number = start.get("line")
    extra = entry.get("extra") or {}
    message = extra.get("message") or ""
    severity = _map_severity(extra.get("severity"))

    return Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=severity,
        rule_id=check_id,
        title=check_id,
        fingerprint=_fingerprint(check_id, file_path, line_number),
        created_at=now,
        updated_at=now,
        file_path=file_path,
        line_number=line_number,
        raw_evidence={"message": message, "metadata": extra.get("metadata") or {}},
        snippet=message,
    )


def _map_severity(raw_severity: str | None) -> FindingSeverity:
    """Translate semgrep's `extra.severity` (D7); any value outside
    `_SEVERITY_MAP` falls back to MEDIUM + a logged warning rather than
    failing the whole scan."""
    severity = _SEVERITY_MAP.get(raw_severity or "")
    if severity is None:
        logger.warning(
            "semgrep reported an unrecognized severity %r — falling back to MEDIUM",
            raw_severity,
        )
        return _UNKNOWN_SEVERITY_FALLBACK
    return severity


def _normalize_path(file_path: str) -> str:
    """Strip the container mount-path prefix (D9) so `Finding.file_path`
    never leaks the container's internal mount layout — confirmed live: an
    absolute scan-target argument makes semgrep emit absolute,
    mount-prefixed paths."""
    return file_path.removeprefix(f"{_TARGET_DIR}/")


def _fingerprint(check_id: str, file_path: str, line_number: int | None) -> str:
    """Deterministic dedup hash — same convention as
    `ast_sast_adapter._fingerprint`/`pip_audit_adapter._fingerprint`: sha256
    hex digest over the fields that identify a distinct violation instance."""
    canonical = f"{check_id}:{file_path}:{line_number}"
    return hashlib.sha256(canonical.encode()).hexdigest()
