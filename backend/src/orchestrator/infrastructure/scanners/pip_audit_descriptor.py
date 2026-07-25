"""Fixed Docker invocation descriptor for pip-audit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult
from orchestrator.infrastructure.scanners.pip_audit_adapter import (
    _MOUNT_PATH,
    _PIP_AUDIT_ARGV,
    _PROBE_ARGV,
    _PROBE_PRESENT_EXIT_CODE,
    _SYNTHETIC_EMPTY_STDOUT,
)

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings


@dataclass(frozen=True, slots=True)
class PipAuditInvocation:
    """Run the fixed manifest probe and, when present, fixed pip-audit argv."""

    image: str
    limits: ResourceLimits
    timeout_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> PipAuditInvocation:
        return cls(
            image=settings.scan_pip_audit_image,
            limits=ResourceLimits(
                memory_mb=settings.scan_memory_limit_mb,
                nano_cpus=int(settings.scan_cpu_limit * 1_000_000_000),
                pids_limit=settings.scan_pids_limit,
            ),
            timeout_seconds=settings.scan_timeout_seconds,
        )

    def run(self, runner: ContainerRunnerPort, volume_name: str) -> RunResult:
        probe = runner.run(
            image=self.image,
            command=list(_PROBE_ARGV),
            volume_name=volume_name,
            mount_path=_MOUNT_PATH,
            read_only_mount=True,
            network_disabled=True,
            limits=self.limits,
            timeout_seconds=self.timeout_seconds,
            tmp_exec=False,
            cleanup_anonymous_volumes=True,
        )
        if probe.timed_out:
            return probe
        if probe.exit_code != _PROBE_PRESENT_EXIT_CODE:
            return RunResult(
                exit_code=0, stdout=_SYNTHETIC_EMPTY_STDOUT, stderr="", timed_out=False
            )
        return runner.run(
            image=self.image,
            command=list(_PIP_AUDIT_ARGV),
            volume_name=volume_name,
            mount_path=_MOUNT_PATH,
            read_only_mount=True,
            network_disabled=False,
            limits=self.limits,
            timeout_seconds=self.timeout_seconds,
            tmp_exec=True,
            cleanup_anonymous_volumes=True,
        )
