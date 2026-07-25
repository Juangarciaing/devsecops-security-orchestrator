"""Active descriptor-based Docker execution for Semgrep."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort, ScanExecutionResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.scanners.semgrep_adapter import SemgrepAdapter
from orchestrator.infrastructure.scanners.semgrep_descriptor import SemgrepInvocation
from orchestrator.infrastructure.vcs.git_checkout import GitCheckout

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings


class SemgrepDockerExecution(ScanExecutionPort):
    """Checkout, invoke Semgrep from its descriptor, parse, and clean up once."""

    def __init__(
        self, runner: ContainerRunnerPort, docker_client: DockerClient, settings: Settings
    ) -> None:
        self._runner = runner
        self._docker_client = docker_client
        self._settings = settings

    def execute(
        self, clone_url: str, ref: str, scan_task_id: uuid.UUID, scanner_type: ScannerType
    ) -> ScanExecutionResult:
        if scanner_type != ScannerType.SEMGREP:
            raise ValueError("SemgrepDockerExecution only supports ScannerType.SEMGREP")
        parser = SemgrepAdapter(self._runner, self._settings)
        with GitCheckout(
            self._runner, self._docker_client, self._settings, cleanup_anonymous_volumes=True
        ).checkout(clone_url, ref) as workspace:
            invocation = SemgrepInvocation.from_settings(self._settings)
            result = invocation.run(self._runner, workspace.volume_name)
        return ScanExecutionResult(workspace.head_sha, parser.parse(result, scan_task_id))
