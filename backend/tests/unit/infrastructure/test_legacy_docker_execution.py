from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.container.legacy_docker_execution import (
    LegacyDockerExecution,
    create_scan_execution,
)


class _Workspace:
    volume_name = "scan-workspace"
    head_sha = "deadbeef"

    def __enter__(self) -> _Workspace:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _Adapter:
    def __init__(self) -> None:
        self.scanned_volume: str | None = None

    def scan(self, volume_name: str) -> RunResult:
        self.scanned_volume = volume_name
        return RunResult(exit_code=0, stdout="report", stderr="", timed_out=False)

    def parse(self, result: RunResult, scan_task_id: uuid.UUID) -> list[str]:
        return [f"{scan_task_id}:{result.stdout}"]


def test_factory_selects_legacy_docker_as_the_only_default() -> None:
    execution = create_scan_execution(MagicMock(), MagicMock(), SimpleNamespace())

    assert isinstance(execution, LegacyDockerExecution)


def test_legacy_execution_delegates_to_existing_checkout_adapter_and_parser(
    monkeypatch,
) -> None:
    from orchestrator.infrastructure.container import legacy_docker_execution

    adapter = _Adapter()
    checkout = MagicMock()
    checkout.checkout.return_value = _Workspace()
    monkeypatch.setattr(legacy_docker_execution, "GitCheckout", lambda *args: checkout)
    monkeypatch.setattr(legacy_docker_execution, "get_adapter", lambda *args: adapter)
    task_id = uuid.uuid4()

    result = LegacyDockerExecution(MagicMock(), MagicMock(), SimpleNamespace()).execute(
        clone_url="https://github.com/acme/public.git",
        ref="main",
        scan_task_id=task_id,
        scanner_type=ScannerType.SECRETS,
    )

    assert result.head_sha == "deadbeef"
    assert result.findings == [f"{task_id}:report"]
    assert adapter.scanned_volume == "scan-workspace"
    checkout.checkout.assert_called_once_with("https://github.com/acme/public.git", "main")
