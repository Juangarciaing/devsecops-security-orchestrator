from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.container import (
    ast_sast_docker_execution,
    semgrep_docker_execution,
)
from orchestrator.infrastructure.container.ast_sast_docker_execution import AstSastDockerExecution
from orchestrator.infrastructure.container.gitleaks_docker_execution import GitleaksDockerExecution
from orchestrator.infrastructure.container.pip_audit_docker_execution import PipAuditDockerExecution
from orchestrator.infrastructure.container.scan_execution_factory import (
    create_scan_execution,
)
from orchestrator.infrastructure.container.semgrep_docker_execution import SemgrepDockerExecution
from orchestrator.infrastructure.scanners.ast_sast_adapter import SastFailedError
from orchestrator.infrastructure.scanners.semgrep_adapter import SemgrepFailedError


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
        scan_sast_image="sast-scanner",
        scan_semgrep_image="semgrep-scanner",
        scan_timeout_seconds=17,
        scan_memory_limit_mb=128,
        scan_cpu_limit=0.5,
        scan_pids_limit=64,
    )


_CASES = [
    (
        ScannerType.SAST,
        ast_sast_docker_execution,
        AstSastDockerExecution,
        ["python", "-m", "sast.cli", "--path", "/checkout/checkout", "--format", "json"],
        '{"findings": []}',
    ),
    (
        ScannerType.SEMGREP,
        semgrep_docker_execution,
        SemgrepDockerExecution,
        [
            "semgrep",
            "scan",
            "--config",
            "/rules",
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            "/checkout/checkout",
        ],
        '{"results": []}',
    ),
]


@pytest.mark.parametrize(
    ("scanner_type", "module", "execution_class", "expected_command", "stdout"), _CASES
)
def test_descriptor_executions_use_fixed_argv_and_owned_volume_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    scanner_type: ScannerType,
    module: object,
    execution_class: type[object],
    expected_command: list[str],
    stdout: str,
) -> None:
    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    monkeypatch.setattr(module, "GitCheckout", lambda *args, **kwargs: checkout)
    runner = MagicMock()
    runner.run.return_value = RunResult(exit_code=0, stdout=stdout, stderr="", timed_out=False)

    execution = execution_class(runner, MagicMock(), _settings())
    execution.execute(
        "https://github.com/acme/repo.git;$(touch pwned)",
        "main;$(touch pwned)",
        uuid.uuid4(),
        scanner_type,
    )

    invocation = runner.run.call_args.kwargs
    assert invocation["command"] == expected_command
    assert "$(touch pwned)" not in invocation["command"]
    assert invocation["network_disabled"] is True
    assert invocation["read_only_mount"] is True
    assert invocation["cleanup_anonymous_volumes"] is True
    assert workspace.exited is True


@pytest.mark.parametrize(("scanner_type", "module", "execution_class", "_", "__"), _CASES)
def test_descriptor_executions_preserve_timeout_and_workspace_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    scanner_type: ScannerType,
    module: object,
    execution_class: type[object],
    _: list[str],
    __: str,
) -> None:
    workspace = _Workspace()
    checkout = MagicMock()
    checkout.checkout.return_value = workspace
    monkeypatch.setattr(module, "GitCheckout", lambda *args, **kwargs: checkout)
    runner = MagicMock()
    runner.run.return_value = RunResult(exit_code=-1, stdout="", stderr="", timed_out=True)

    failure = SastFailedError if scanner_type == ScannerType.SAST else SemgrepFailedError
    with pytest.raises(failure, match="timed out"):
        execution_class(runner, MagicMock(), _settings()).execute(
            "https://github.com/acme/public.git", "main", uuid.uuid4(), scanner_type
        )

    assert workspace.exited is True


def test_descriptor_executions_preserve_parser_findings_and_factory_has_one_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for scanner_type, module, execution_class, _, __ in _CASES:
        report = (
            {"findings": [{"rule_id": "ast-rule", "file": "/checkout/checkout/app.py", "line": 7}]}
            if scanner_type == ScannerType.SAST
            else {
                "results": [
                    {
                        "check_id": "semgrep-rule",
                        "path": "/checkout/checkout/app.py",
                        "start": {"line": 8},
                        "extra": {},
                    }
                ]
            }
        )
        workspace = _Workspace()
        checkout = MagicMock()
        checkout.checkout.return_value = workspace
        monkeypatch.setattr(
            module, "GitCheckout", lambda *args, _checkout=checkout, **kwargs: _checkout
        )
        runner = MagicMock()
        runner.run.return_value = RunResult(
            exit_code=0, stdout=json.dumps(report), stderr="", timed_out=False
        )
        result = execution_class(runner, MagicMock(), _settings()).execute(
            "https://github.com/acme/public.git", "main", uuid.uuid4(), scanner_type
        )
        assert result.head_sha == "deadbeef"
        assert result.findings[0].file_path == "app.py"
        assert workspace.exited is True

    dependencies = (MagicMock(), MagicMock(), _settings())
    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SECRETS), GitleaksDockerExecution
    )
    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SAST),
        AstSastDockerExecution,
    )
    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SEMGREP),
        SemgrepDockerExecution,
    )
    assert isinstance(
        create_scan_execution(*dependencies, ScannerType.SCA), PipAuditDockerExecution
    )
