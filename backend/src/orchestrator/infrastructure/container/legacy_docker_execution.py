"""Active Docker implementation that preserves the existing scan flow exactly."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort, ScanExecutionResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.container.ast_sast_docker_execution import AstSastDockerExecution
from orchestrator.infrastructure.container.gitleaks_docker_execution import GitleaksDockerExecution
from orchestrator.infrastructure.container.pip_audit_docker_execution import PipAuditDockerExecution
from orchestrator.infrastructure.container.semgrep_docker_execution import SemgrepDockerExecution
from orchestrator.infrastructure.scanners.registry import get_adapter
from orchestrator.infrastructure.vcs.git_checkout import GitCheckout

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings


class LegacyDockerExecution(ScanExecutionPort):
    """Delegate unchanged Docker checkout, scanner execution, parsing and cleanup."""

    def __init__(
        self, runner: ContainerRunnerPort, docker_client: DockerClient, settings: Settings
    ) -> None:
        self._runner = runner
        self._docker_client = docker_client
        self._settings = settings

    def execute(
        self,
        clone_url: str,
        ref: str,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
    ) -> ScanExecutionResult:
        if scanner_type in {ScannerType.SECRETS, ScannerType.SAST, ScannerType.SEMGREP}:
            raise ValueError(f"{scanner_type.value} must use its descriptor Docker execution")
        adapter = get_adapter(scanner_type, self._runner, self._settings)
        with GitCheckout(self._runner, self._docker_client, self._settings).checkout(
            clone_url, ref
        ) as workspace:
            result = adapter.scan(workspace.volume_name)
        return ScanExecutionResult(workspace.head_sha, adapter.parse(result, scan_task_id))


def create_scan_execution(
    runner: ContainerRunnerPort,
    docker_client: DockerClient,
    settings: Settings,
    scanner_type: ScannerType,
) -> ScanExecutionPort:
    """Route all active scanner types to exactly one descriptor executor."""
    if scanner_type == ScannerType.SECRETS:
        return GitleaksDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SAST:
        return AstSastDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SEMGREP:
        return SemgrepDockerExecution(runner, docker_client, settings)
    if scanner_type == ScannerType.SCA:
        return PipAuditDockerExecution(runner, docker_client, settings)
    return LegacyDockerExecution(runner, docker_client, settings)
