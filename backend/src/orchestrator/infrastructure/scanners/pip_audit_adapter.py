"""`PipAuditAdapter` — runs pip-audit against a checked-out volume and parses
its JSON report into `Finding`s (Module 11, tasks 1.4-1.6).

Implements `ScannerAdapterPort` (Module 7 D1), mirroring `GitleaksAdapter`'s
shape (`scan()`/`parse()`/`supports()`), selected via
`infrastructure.scanners.registry.get_adapter(ScannerType.SCA, ...)`.

## Manifest short-circuit (D3)
The adapter cannot stat the checked-out volume directly (it only ever
receives `volume_name`), so `scan()` first launches a hardened,
`network_disabled=True` PROBE container (same pinned image, argv
`["python", "-c", "..."]`) that checks whether `requirements.txt` exists in
the mounted checkout. Exit `0` (present) -> the real, network-enabled
pip-audit container runs. Exit non-zero (absent) -> `scan()` returns a
synthetic `RunResult` carrying `{"dependencies": []}` WITHOUT ever launching
the network-enabled container — avoids a guaranteed no-op network egress.

## Parse-driven success (D4)
Unlike Gitleaks, pip-audit has no `--exit-code` disambiguator: exit `1`
means EITHER "vulnerabilities found" OR "a genuine tool error" — the two are
indistinguishable by exit code alone. `parse()` therefore ignores
`result.exit_code` entirely: `timed_out=True` -> `PipAuditFailedError`;
valid JSON with a `dependencies` key on stdout -> success (0..N findings);
empty/malformed/missing-key stdout -> `PipAuditFailedError` (message from
stderr when available).
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
#: files resolve at `/checkout/checkout` (same convention as
#: `gitleaks_adapter._TARGET_DIR`).
_TARGET_REQUIREMENTS = "/checkout/checkout/requirements.txt"

#: Pre-flight probe argv (D3) — `python` is guaranteed present in the
#: pip-audit image (it's a `python:3.12-slim` derivative). Exit `0` iff the
#: manifest exists on the read-only mount; exit `1` otherwise.
_PROBE_ARGV: tuple[str, ...] = (
    "python",
    "-c",
    f"import os,sys;sys.exit(0 if os.path.isfile({_TARGET_REQUIREMENTS!r}) else 1)",
)
_PROBE_PRESENT_EXIT_CODE = 0

_PIP_AUDIT_ARGV: tuple[str, ...] = (
    "pip-audit",
    "--format=json",
    "--no-deps",
    "--progress-spinner=off",
    "--cache-dir=/tmp/pip-audit-cache",
    "-r",
    _TARGET_REQUIREMENTS,
)

#: Synthetic zero-findings report returned by `scan()` when the probe finds
#: no manifest — keeps `parse()` purely JSON-driven with no special-casing
#: for "manifest absent" (D3).
_SYNTHETIC_EMPTY_STDOUT = json.dumps({"dependencies": []})

#: pip-audit has no built-in severity concept — every finding defaults to
#: MEDIUM (design D5: adapter-level constant, not a new `Settings` field).
DEFAULT_SEVERITY = FindingSeverity.MEDIUM

_REQUIREMENTS_FILE_PATH = "requirements.txt"


class PipAuditFailedError(Exception):
    """A genuine adapter/tool failure — never raised for "vulns found" (D4)."""


class PipAuditAdapter(ScannerAdapterPort):
    """Launches the pinned pip-audit image against a checked-out volume (D3/D4).

    Implements `ScannerAdapterPort` (Module 7 D1) — selected via
    `infrastructure.scanners.registry.get_adapter(ScannerType.SCA, ...)`.
    """

    def __init__(self, runner: ContainerRunnerPort, settings: Settings) -> None:
        self._runner = runner
        self._settings = settings

    def scan(self, volume_name: str) -> RunResult:
        """Probe for `requirements.txt`, then run pip-audit iff present (D3).

        Returns the raw `RunResult` — callers pass it to `parse()` to get
        `Finding`s (kept separate so `parse()` stays a pure, easily
        triangulated method with no container dependency).
        """
        probe_result = self._runner.run(
            image=self._settings.scan_pip_audit_image,
            command=list(_PROBE_ARGV),
            volume_name=volume_name,
            mount_path=_MOUNT_PATH,
            read_only_mount=True,
            network_disabled=True,
            limits=self._resource_limits(),
            timeout_seconds=self._settings.scan_timeout_seconds,
        )
        if probe_result.exit_code != _PROBE_PRESENT_EXIT_CODE:
            return RunResult(
                exit_code=0, stdout=_SYNTHETIC_EMPTY_STDOUT, stderr="", timed_out=False
            )

        return self._runner.run(
            image=self._settings.scan_pip_audit_image,
            command=list(_PIP_AUDIT_ARGV),
            volume_name=volume_name,
            mount_path=_MOUNT_PATH,
            read_only_mount=True,
            network_disabled=False,
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
        """Interpret one pip-audit `RunResult` per the D4 parse-driven contract.

        Zero vulnerabilities across every dependency is a valid, successful
        outcome — returns `[]`, not an error.
        """
        if result.timed_out:
            raise PipAuditFailedError(
                f"pip-audit timed out (exit_code={result.exit_code}, stderr={result.stderr!r})"
            )

        report = _parse_json_report(result.stdout, result.stderr)
        now = datetime.now(UTC).replace(tzinfo=None)
        findings: list[Finding] = []
        for dependency in report.get("dependencies", []):
            name = dependency.get("name") or "unknown-package"
            version = dependency.get("version") or ""
            for vuln in dependency.get("vulns") or []:
                findings.append(
                    _vuln_to_finding(name, version, vuln, scan_task_id, default_severity, now)
                )
        return findings

    def supports(self, scanner_type: ScannerType) -> bool:
        """`PipAuditAdapter` only handles `ScannerType.SCA`."""
        return scanner_type == ScannerType.SCA

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )


def _parse_json_report(stdout: str, stderr: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        raise PipAuditFailedError(f"empty pip-audit output: {stderr}")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PipAuditFailedError(f"malformed pip-audit JSON report: {exc}") from exc
    if not isinstance(parsed, dict) or "dependencies" not in parsed:
        raise PipAuditFailedError(
            f"malformed pip-audit JSON report: missing 'dependencies' key (stderr={stderr!r})"
        )
    return parsed


def _vuln_to_finding(
    name: str,
    version: str,
    vuln: dict[str, Any],
    scan_task_id: uuid.UUID,
    severity: FindingSeverity,
    now: datetime,
) -> Finding:
    vuln_id = vuln.get("id") or "unknown-vuln"
    description = vuln.get("description") or ""
    fix_versions = vuln.get("fix_versions") or []
    aliases = vuln.get("aliases") or []
    snippet = f"{description} (fix: {', '.join(fix_versions)})" if fix_versions else description

    return Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=severity,
        rule_id=vuln_id,
        title=f"{name} {version}: {vuln_id}",
        fingerprint=_fingerprint(vuln_id, name, version),
        created_at=now,
        updated_at=now,
        file_path=_REQUIREMENTS_FILE_PATH,
        raw_evidence={
            "description": description,
            "fix_versions": fix_versions,
            "aliases": aliases,
        },
        snippet=snippet,
    )


def _fingerprint(vuln_id: str, name: str, version: str) -> str:
    """Deterministic dedup hash — same convention as
    `gitleaks_adapter._fingerprint`: sha256 hex digest over the fields that
    identify a distinct vulnerability instance."""
    canonical = f"{vuln_id}:{name}:{version}"
    return hashlib.sha256(canonical.encode()).hexdigest()
