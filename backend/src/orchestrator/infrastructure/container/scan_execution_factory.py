"""Route each supported `ScannerType` to exactly one descriptor Docker execution.

PR5b (Module 13c): replaces `legacy_docker_execution.create_scan_execution`'s
dormant fallback branch. Every one of the four active scanner types
(`SECRETS`, `SAST`, `SEMGREP`, `SCA`) resolves to its own descriptor
executor; any other `ScannerType` (e.g. `DAST`, `IAC`) is unsupported and
raises `UnsupportedScannerTypeError` directly — there is no shared/legacy
execution path left to fall back to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.container.ast_sast_docker_execution import AstSastDockerExecution
from orchestrator.infrastructure.container.gitleaks_docker_execution import GitleaksDockerExecution
from orchestrator.infrastructure.container.pip_audit_docker_execution import PipAuditDockerExecution
from orchestrator.infrastructure.container.semgrep_docker_execution import SemgrepDockerExecution

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort
    from orchestrator.infrastructure.config.settings import Settings


class UnsupportedScannerTypeError(ValueError):
    """Raised by `create_scan_execution()` when `scanner_type` has no
    descriptor Docker execution registered."""

    def __init__(self, scanner_type: ScannerType) -> None:
        super().__init__(
            f"no descriptor Docker execution registered for scanner type: {scanner_type.value}"
        )
        self.scanner_type = scanner_type


def create_scan_execution(
    runner: ContainerRunnerPort,
    docker_client: DockerClient,
    settings: Settings,
    scanner_type: ScannerType,
) -> ScanExecutionPort:
    """Select exactly one descriptor executor for `scanner_type`.

    Raises `UnsupportedScannerTypeError` for any scanner type without a
    descriptor registration — never delegates to a shared/legacy executor.
    """
    if scanner_type == ScannerType.SECRETS:
        return GitleaksDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SAST:
        return AstSastDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SEMGREP:
        return SemgrepDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SCA:
        return PipAuditDockerExecution(runner, docker_client, settings)
    raise UnsupportedScannerTypeError(scanner_type)
