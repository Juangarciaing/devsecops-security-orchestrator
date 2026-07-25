"""The single Docker invocation descriptor for Gitleaks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings


_MOUNT_PATH = "/checkout"
_TARGET_DIR = "/checkout/checkout"
_GITLEAKS_ARGV: tuple[str, ...] = (
    "dir",
    _TARGET_DIR,
    "--report-format=json",
    "--report-path=/dev/stdout",
    "--exit-code=2",
    "--no-banner",
)


@dataclass(frozen=True, slots=True)
class GitleaksInvocation:
    """Fixed argv-only Gitleaks invocation over a checked-out named volume."""

    image: str
    command: tuple[str, ...]
    mount_path: str
    limits: ResourceLimits
    timeout_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> GitleaksInvocation:
        return cls(
            image=settings.scan_container_image,
            command=_GITLEAKS_ARGV,
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
