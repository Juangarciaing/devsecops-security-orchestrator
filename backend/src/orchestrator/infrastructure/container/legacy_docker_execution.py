"""Active Docker implementation that preserves the existing scan flow exactly."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort, ScanExecutionResult
from orchestrator.domain.value_objects.enums import ScannerType
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
        adapter = get_adapter(scanner_type, self._runner, self._settings)
        with GitCheckout(self._runner, self._docker_client, self._settings).checkout(
            clone_url, ref
        ) as workspace:
            result = adapter.scan(workspace.volume_name)
        return ScanExecutionResult(workspace.head_sha, adapter.parse(result, scan_task_id))


def create_scan_execution(
    runner: ContainerRunnerPort, docker_client: DockerClient, settings: Settings
) -> ScanExecutionPort:
    """Create the sole PR1 execution path; later backends extend this factory."""
    return LegacyDockerExecution(runner, docker_client, settings)
