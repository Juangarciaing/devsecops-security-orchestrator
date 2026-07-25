"""Fixed Docker invocation descriptor for Semgrep."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult
from orchestrator.infrastructure.scanners.semgrep_adapter import _MOUNT_PATH, _SEMGREP_ARGV

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings


@dataclass(frozen=True, slots=True)
class SemgrepInvocation:
    """Fixed argv-only Semgrep invocation over an owned named volume."""

    image: str
    command: tuple[str, ...]
    mount_path: str
    limits: ResourceLimits
    timeout_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> SemgrepInvocation:
        return cls(
            image=settings.scan_semgrep_image,
            command=_SEMGREP_ARGV,
            mount_path=_MOUNT_PATH,
            limits=ResourceLimits(
                memory_mb=settings.scan_memory_limit_mb,
                nano_cpus=int(settings.scan_cpu_limit * 1_000_000_000),
                pids_limit=settings.scan_pids_limit,
            ),
            timeout_seconds=settings.scan_timeout_seconds,
        )

    def run(self, runner: ContainerRunnerPort, volume_name: str) -> RunResult:
        return runner.run(
            image=self.image,
            command=list(self.command),
            volume_name=volume_name,
            mount_path=self.mount_path,
            read_only_mount=True,
            network_disabled=True,
            limits=self.limits,
            timeout_seconds=self.timeout_seconds,
            cleanup_anonymous_volumes=True,
        )
