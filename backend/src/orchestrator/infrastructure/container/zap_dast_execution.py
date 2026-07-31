"""`ZapDastDockerExecution` — the DAST target-scan executor (dast-scanner
design D3/D4/D6/D7, PR5b-ii, tasks 5.2/5.12).

Wires every already-landed PR5 building block together in one fixed call
order (test-asserted, task 5.2):

1. `resolve_and_authorize(target_url)` (PR3, design D3) — fail-closed DNS
   re-resolution, the narrowest possible check-to-create window: NOTHING
   else runs if this raises `TargetResolutionError`/`InvalidTargetUrlError`.
2. `ensure_dast_network(docker_client, settings)` (PR5b-i, design D4).
3. An ephemeral named volume + a `chmod 0777` init container — mirrors
   `GitCheckout._prepare_volume_permissions` byte-for-byte (same rationale:
   a freshly created volume's mountpoint is root-owned on the host, and
   every scanner container this system launches runs as a non-root user).
4. Run 1 — the ZAP baseline scan itself, joined to the dedicated network,
   with the design D6 rung-3 override the PR4 live-Docker spike proved
   necessary: `user="1000:1000"` + a `/home/zap` tmpfs owned by the same
   uid:gid, and `env={"HOME": "/zap/wrk"}` (ZAP resolves its home directory
   via native `getpwuid()` and ignores `$HOME` at this repo's default
   hardened uid).
5. Run 2 — `cat report.json` against the SAME volume, this port's PLAIN
   default hardening (`network_disabled=True`, no `user`/`extra_tmpfs`
   override) — mirrors `GitCheckout`'s existing "second argv-only run on
   the same image reads a value off the volume via stdout" pattern
   (`git rev-parse HEAD`), design D7.
6. `ZapAdapter.parse(run2_result, scan_task_id)` (PR5a).
7. Volume cleanup in a `finally` — mirrors `Workspace`'s cleanup shape,
   guaranteed regardless of whether parsing succeeds or raises.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from orchestrator.domain.ports.container_runner_port import ResourceLimits, TmpfsMount
from orchestrator.domain.ports.target_scan_execution_port import (
    TargetScanExecutionPort,
    TargetScanExecutionResult,
)
from orchestrator.infrastructure.container.dast_network import ensure_dast_network
from orchestrator.infrastructure.scanners.zap_adapter import ZapAdapter
from orchestrator.infrastructure.scanners.zap_descriptor import (
    _ZAP_REPORT,
    _ZAP_WORK_DIR,
    build_zap_argv,
)
from orchestrator.infrastructure.security.dns_target_resolver import resolve_and_authorize

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.domain.value_objects.enums import ScannerType
    from orchestrator.infrastructure.config.settings import Settings

#: Design D6 rung 3 (PR4 live-Docker spike outcome, load-bearing): ZAP's
#: `zap` user resolves its home directory via native `getpwuid()` and
#: ignores `$HOME` at this repo's default hardened `65532:65532` uid — the
#: upstream image's own `zap` user is `1000:1000`, so this executor MUST
#: override `user=` for run 1 only, plus a writable tmpfs at `/home/zap`
#: owned by the same uid:gid. Never a global relaxation: run 2 (the report
#: readback) gets none of this.
_ZAP_USER = "1000:1000"
_ZAP_HOME_TMPFS = TmpfsMount("/home/zap", uid=1000, gid=1000, size_mb=512)
_ZAP_ENV = {"HOME": _ZAP_WORK_DIR}
_ZAP_REPORT_PATH = f"{_ZAP_WORK_DIR}/{_ZAP_REPORT}"


class ZapDastDockerExecution(TargetScanExecutionPort):
    """Guard -> network -> volume -> 2 runs -> parse -> cleanup."""

    def __init__(
        self, runner: ContainerRunnerPort, docker_client: DockerClient, settings: Settings
    ) -> None:
        self._runner = runner
        self._docker_client = docker_client
        self._settings = settings

    def execute(
        self,
        target_url: str,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
    ) -> TargetScanExecutionResult:
        """Run one DAST scan attempt against `target_url`.

        `asyncio.run(...)` is safe here ONLY because `TargetScanExecutionPort
        .execute()`'s contract guarantees callers invoke it OUTSIDE any
        existing asyncio event loop (Module 6 D3, mirrored from
        `ScanExecutionPort`) — this is the one narrow bridge between the
        async SSRF guard and this otherwise-sync executor; nothing else in
        this method is threaded through `async`/`await`.
        """
        authorized_url = asyncio.run(resolve_and_authorize(target_url))

        network_name = ensure_dast_network(self._docker_client, self._settings)

        volume_name = f"dast-{uuid.uuid4().hex}"
        self._docker_client.volumes.create(name=volume_name)
        try:
            self._prepare_volume_permissions(volume_name)
            limits = self._resource_limits()

            self._runner.run(
                image=self._settings.scan_zap_image,
                command=list(build_zap_argv(authorized_url)),
                volume_name=volume_name,
                mount_path=_ZAP_WORK_DIR,
                read_only_mount=False,
                network_disabled=False,
                network_name=network_name,
                limits=limits,
                timeout_seconds=self._settings.dast_timeout_seconds,
                env=dict(_ZAP_ENV),
                user=_ZAP_USER,
                extra_tmpfs=(_ZAP_HOME_TMPFS,),
                cleanup_anonymous_volumes=True,
            )

            report_result = self._runner.run(
                image=self._settings.scan_zap_image,
                command=["cat", _ZAP_REPORT_PATH],
                volume_name=volume_name,
                mount_path=_ZAP_WORK_DIR,
                read_only_mount=True,
                network_disabled=True,
                limits=limits,
                timeout_seconds=self._settings.dast_timeout_seconds,
                cleanup_anonymous_volumes=True,
            )

            findings = ZapAdapter(self._runner, self._settings).parse(
                report_result, scan_task_id
            )
        finally:
            self._docker_client.volumes.get(volume_name).remove(force=True)

        return TargetScanExecutionResult(findings=findings)

    def _prepare_volume_permissions(self, volume_name: str) -> None:
        """`chmod 0777` the freshly created (root-owned) volume mountpoint —
        mirrors `GitCheckout._prepare_volume_permissions` exactly: this
        step genuinely needs root (to chmod a root-owned directory) and
        stays narrowly scoped (argv-only, hardcoded, no network, against a
        volume with zero content yet)."""
        run_kwargs: dict[str, Any] = {
            "image": self._settings.scan_git_image,
            "entrypoint": "chmod",
            "command": ["0777", _ZAP_WORK_DIR],
            "volumes": {volume_name: {"bind": _ZAP_WORK_DIR, "mode": "rw"}},
            "network_mode": "none",
            "remove": True,
        }
        self._docker_client.containers.run(**run_kwargs)

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )
