from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.scanners.pip_audit_adapter import PipAuditFailedError


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
        scan_pip_audit_image="pip-audit",
        scan_timeout_seconds=17,
        scan_memory_limit_mb=128,
        scan_cpu_limit=0.5,
        scan_pids_limit=64,
    )


def _execution(monkeypatch: pytest.MonkeyPatch, runner: MagicMock) -> tuple[object, _Workspace]:
    from orchestrator.infrastructure.container import pip_audit_docker_execution

    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    monkeypatch.setattr(pip_audit_docker_execution, "GitCheckout", lambda *args, **kwargs: checkout)
    return (
        pip_audit_docker_execution.PipAuditDockerExecution(runner, MagicMock(), _settings()),
        workspace,
    )


def test_descriptor_execution_uses_fixed_probe_then_tmp_exec_audit_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = MagicMock()
    runner.run.side_effect = [
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(
            exit_code=1,
            stdout=json.dumps(
                {
                    "dependencies": [
                        {
                            "name": "requests",
                            "version": "2.19.0",
                            "vulns": [{"id": "PYSEC-2018-28", "description": "known vuln"}],
                        }
                    ]
                }
            ),
            stderr="",
            timed_out=False,
        ),
    ]
    execution, workspace = _execution(monkeypatch, runner)
    malicious_url = "https://github.com/acme/repo.git;$(touch pwned)"
    malicious_ref = "main;$(touch pwned)"

    result = execution.execute(malicious_url, malicious_ref, uuid.uuid4(), ScannerType.SCA)

    assert result.head_sha == "deadbeef"
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "PYSEC-2018-28"
    probe, audit = (call.kwargs for call in runner.run.call_args_list)
    assert probe["network_disabled"] is True and probe["tmp_exec"] is False
    assert audit["command"] == [
        "pip-audit",
        "--format=json",
        "--no-deps",
        "--progress-spinner=off",
        "--cache-dir=/tmp/pip-audit-cache",
        "-r",
        "/checkout/checkout/requirements.txt",
    ]
    assert audit["network_disabled"] is False and audit["tmp_exec"] is True
    assert malicious_url not in audit["command"] and malicious_ref not in audit["command"]
    assert audit["cleanup_anonymous_volumes"] is True and workspace.exited is True


def test_descriptor_execution_short_circuits_absent_manifest_and_preserves_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    absent_runner = MagicMock()
    absent_runner.run.return_value = RunResult(exit_code=1, stdout="", stderr="", timed_out=False)
    execution, workspace = _execution(monkeypatch, absent_runner)

    result = execution.execute(
        "https://github.com/acme/public.git", "main", uuid.uuid4(), ScannerType.SCA
    )

    assert result.findings == []
    assert absent_runner.run.call_count == 1 and workspace.exited is True

    timeout_runner = MagicMock()
    timeout_runner.run.return_value = RunResult(exit_code=-1, stdout="", stderr="", timed_out=True)
    execution, timeout_workspace = _execution(monkeypatch, timeout_runner)
    with pytest.raises(PipAuditFailedError, match="timed out"):
        execution.execute(
            "https://github.com/acme/public.git", "main", uuid.uuid4(), ScannerType.SCA
        )
    assert timeout_runner.run.call_count == 1 and timeout_workspace.exited is True
