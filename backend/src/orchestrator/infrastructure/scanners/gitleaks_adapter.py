"""`GitleaksAdapter` — runs Gitleaks against a checked-out volume and parses
its JSON report into `Finding`s (Module 6 D4, tasks 2.1-2.3).

Implements `ScannerAdapterPort` (Module 7 D1, tasks 2.1-2.2): `parse()` is a
method here, not a module-level function — the old module-level `parse()`
shim was DELETED once this method existed, so there is exactly one entry
point.

## Exit-code contract (D4)
Gitleaks' own source (`cmd/root.go`, confirmed against the real v8.30.1
release, not merely inferred from docs) exits 1 whenever `detector.DetectSource`
returns a non-nil `err` — REGARDLESS of `--exit-code` — and exits the
`--exit-code` value ONLY when `len(findings) != 0` and `err == nil`. The
proposal's original `--exit-code=1` for "leaks found" would therefore be
indistinguishable from a genuine tool error; `--exit-code=2` disambiguates:

- `0`  -> clean scan, zero findings (success)
- `2`  -> leaks found, JSON report on stdout (success, N findings)
- `1`  -> genuine Gitleaks error (bad config, scan failure) — never leaks
- `126`-> unknown flag / misuse
- any other code, `timed_out=True`, or malformed JSON on exit 2 -> failure

Exit 0/2 with findings present is the ONLY success path that yields
`Finding`s; every other outcome raises `GitleaksFailedError` (never
conflated with "leaks found" — D5's transient/permanent split happens one
layer up, in the worker task that catches this).
"""

from __future__ import annotations

import hashlib
import json
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

_MOUNT_PATH = "/checkout"
#: `GitCheckout` clones into a `checkout/` subdir of the SHARED volume root
#: (its own mount path is `/workspace`, so on-disk that subdir is
#: `/workspace/checkout`); mounted here at `/checkout` instead, the same
#: files resolve at `/checkout/checkout`.
_TARGET_DIR = "/checkout/checkout"
_GITLEAKS_ARGV: tuple[str, ...] = (
    "dir",
    _TARGET_DIR,
    "--report-format=json",
    "--report-path=/dev/stdout",
    "--exit-code=2",
    "--no-banner",
)
_LEAKS_FOUND_EXIT_CODE = 2
_CLEAN_EXIT_CODE = 0

#: Gitleaks has no built-in severity concept — every finding defaults to
#: HIGH (Reconciled #3: adapter-level constant, not a new `Settings` field).
DEFAULT_SEVERITY = FindingSeverity.HIGH


class GitleaksFailedError(Exception):
    """A genuine adapter/tool failure — never raised for "leaks found" (D4)."""


class GitleaksAdapter(ScannerAdapterPort):
    """Launches the pinned Gitleaks image against a checked-out volume (D4).

    Implements `ScannerAdapterPort` (Module 7 D1) — selected via
    `infrastructure.scanners.registry.get_adapter(ScannerType.SECRETS, ...)`.
    """

    def __init__(self, runner: ContainerRunnerPort, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    def scan(self, volume_name: str) -> RunResult:
        """Run Gitleaks read-only, network-disabled, against `volume_name`.

        Returns the raw `RunResult` — callers pass it to `parse()` to get
        `Finding`s (kept separate so `parse()` stays a pure, easily
        triangulated method with no container dependency).
        """
        return self._runner.run(
            image=self._settings.scan_container_image,
            command=list(_GITLEAKS_ARGV),
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
        *,
        default_severity: FindingSeverity = DEFAULT_SEVERITY,
    ) -> list[Finding]:
        """Interpret one Gitleaks `RunResult` per the D4 exit-code contract.

        Zero findings on a clean repo (exit 0) is a valid, successful
        outcome — returns `[]`, not an error.
        """
        if result.timed_out:
            raise GitleaksFailedError(
                f"gitleaks timed out (exit_code={result.exit_code}, stderr={result.stderr!r})"
            )
        if result.exit_code == _CLEAN_EXIT_CODE:
            return []
        if result.exit_code != _LEAKS_FOUND_EXIT_CODE:
            raise GitleaksFailedError(
                f"gitleaks exited {result.exit_code} (genuine failure, not leaks-found): "
                f"{result.stderr}"
            )

        entries = _parse_json_report(result.stdout)
        now = datetime.now(UTC).replace(tzinfo=None)
        return [_entry_to_finding(entry, scan_task_id, default_severity, now) for entry in entries]

    def supports(self, scanner_type: ScannerType) -> bool:
        """`GitleaksAdapter` only handles `ScannerType.SECRETS`."""
        return scanner_type == ScannerType.SECRETS

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )


def _parse_json_report(stdout: str) -> list[dict[str, Any]]:
    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GitleaksFailedError(f"malformed gitleaks JSON report: {exc}") from exc
    if not isinstance(parsed, list):
        raise GitleaksFailedError(
            f"malformed gitleaks JSON report: expected a list, got {type(parsed).__name__}"
        )
    return parsed


def _entry_to_finding(
    entry: dict[str, Any],
    scan_task_id: uuid.UUID,
    severity: FindingSeverity,
    now: datetime,
) -> Finding:
    rule_id = entry.get("RuleID") or "unknown-rule"
    description = entry.get("Description")
    title = description if description else rule_id
    file_path = entry.get("File")
    line_number = entry.get("StartLine")
    secret = entry.get("Secret", "")

    return Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=severity,
        rule_id=rule_id,
        title=title,
        fingerprint=_fingerprint(rule_id, file_path, line_number, secret),
        created_at=now,
        updated_at=now,
        file_path=file_path,
        line_number=line_number,
        raw_evidence={
            "secret": secret,
            "match": entry.get("Match", ""),
            "commit": entry.get("Commit", ""),
        },
        snippet=secret,
    )


def _fingerprint(rule_id: str, file_path: str | None, line_number: int | None, secret: str) -> str:
    """Deterministic dedup hash — same convention as the placeholder Finding's
    `_placeholder_fingerprint` (Module 5): sha256 hex digest over the fields
    that identify a distinct leak instance."""
    canonical = f"{rule_id}:{file_path}:{line_number}:{secret}"
    return hashlib.sha256(canonical.encode()).hexdigest()
