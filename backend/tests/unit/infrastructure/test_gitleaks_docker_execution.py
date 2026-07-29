from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError


class _Workspace:
    volume_name = "scan-workspace"
    head_sha = "deadbeef"

    def __init__(self) -> None:
        self.exited = False

    def __enter__(self) -> _Workspace:
        return self

    def __exit__(self, *args: object) -> None:
        self.exited = True


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        scan_container_image="gitleaks",
        scan_timeout_seconds=17,
        scan_memory_limit_mb=128,
        scan_cpu_limit=0.5,
        scan_pids_limit=64,
    )


def test_gitleaks_descriptor_execution_routes_only_secrets_and_uses_fixed_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orchestrator.infrastructure.container import gitleaks_docker_execution

    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    runner = MagicMock()
    runner.run.return_value = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)
    monkeypatch.setattr(gitleaks_docker_execution, "GitCheckout", lambda *args, **kwargs: checkout)
    task_id = uuid.uuid4()
    malicious_url = "https://github.com/acme/repo.git;$(touch pwned)"
    malicious_ref = "main;$(touch pwned)"

    result = gitleaks_docker_execution.GitleaksDockerExecution(
        runner, MagicMock(), _settings()
    ).execute(malicious_url, malicious_ref, task_id, ScannerType.SECRETS)

    assert result.head_sha == "deadbeef"
    assert result.findings == []
    checkout.checkout.assert_called_once_with(malicious_url, malicious_ref, credential=None)
    runner.run.assert_called_once()
    invocation = runner.run.call_args.kwargs
    assert invocation["command"] == [
        "dir",
        "/checkout/checkout",
        "--report-format=json",
        "--report-path=/dev/stdout",
        "--exit-code=2",
        "--no-banner",
    ]
    assert malicious_url not in invocation["command"]
    assert malicious_ref not in invocation["command"]
    assert invocation["read_only_mount"] is True
    assert invocation["network_disabled"] is True
    assert invocation["timeout_seconds"] == 17
    assert workspace.exited is True


def test_gitleaks_descriptor_execution_preserves_timeout_failure_and_workspace_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orchestrator.infrastructure.container import gitleaks_docker_execution

    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    runner = MagicMock()
    runner.run.return_value = RunResult(exit_code=-1, stdout="", stderr="", timed_out=True)
    monkeypatch.setattr(gitleaks_docker_execution, "GitCheckout", lambda *args, **kwargs: checkout)

    execution = gitleaks_docker_execution.GitleaksDockerExecution(runner, MagicMock(), _settings())

    with pytest.raises(GitleaksFailedError, match="timed out"):
        execution.execute(
            "https://github.com/acme/public.git", "main", uuid.uuid4(), ScannerType.SECRETS
        )

    assert workspace.exited is True


def test_gitleaks_descriptor_execution_preserves_parser_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orchestrator.infrastructure.container import gitleaks_docker_execution

    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    runner = MagicMock()
    runner.run.return_value = RunResult(
        exit_code=2,
        stdout=json.dumps(
            [
                {
                    "RuleID": "generic-api-key",
                    "Description": "Generic API Key",
                    "File": "app.py",
                    "StartLine": 7,
                    "Secret": "synthetic-secret",
                }
            ]
        ),
        stderr="",
        timed_out=False,
    )
    monkeypatch.setattr(gitleaks_docker_execution, "GitCheckout", lambda *args, **kwargs: checkout)
    task_id = uuid.uuid4()

    result = gitleaks_docker_execution.GitleaksDockerExecution(
        runner, MagicMock(), _settings()
    ).execute("https://github.com/acme/public.git", "main", task_id, ScannerType.SECRETS)

    assert len(result.findings) == 1
    assert result.findings[0].scan_task_id == task_id
    assert result.findings[0].rule_id == "generic-api-key"
    assert result.findings[0].file_path == "app.py"
    assert workspace.exited is True


def test_gitleaks_descriptor_execution_threads_credential_into_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR5 (task 5.13): a supplied `credential` reaches `GitCheckout.checkout()`
    unchanged; the scanner invocation itself never sees it."""
    from orchestrator.domain.value_objects.secret import Secret
    from orchestrator.infrastructure.container import gitleaks_docker_execution

    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    runner = MagicMock()
    runner.run.return_value = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)
    monkeypatch.setattr(gitleaks_docker_execution, "GitCheckout", lambda *args, **kwargs: checkout)
    credential = Secret("ghp_should-only-reach-checkout")

    gitleaks_docker_execution.GitleaksDockerExecution(runner, MagicMock(), _settings()).execute(
        "https://github.com/acme/private.git",
        "main",
        uuid.uuid4(),
        ScannerType.SECRETS,
        credential=credential,
    )

    checkout.checkout.assert_called_once_with(
        "https://github.com/acme/private.git", "main", credential=credential
    )
    invocation = runner.run.call_args.kwargs
    assert "env" not in invocation


def test_factory_preserves_gitleaks_descriptor_execution() -> None:
    from orchestrator.infrastructure.container.gitleaks_docker_execution import (
        GitleaksDockerExecution,
    )
    from orchestrator.infrastructure.container.pip_audit_docker_execution import (
        PipAuditDockerExecution,
    )
    from orchestrator.infrastructure.container.scan_execution_factory import create_scan_execution

    dependencies = (MagicMock(), MagicMock(), SimpleNamespace())

    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SECRETS), GitleaksDockerExecution
    )
    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SCA), PipAuditDockerExecution
    )
