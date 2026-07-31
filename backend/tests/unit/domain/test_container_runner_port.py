"""`ContainerRunnerPort` MUST be a SYNC ABC (Module 6 D3 — container
orchestration is blocking I/O, unlike the async repository ports) and MUST
stay framework-free: no `docker` SDK import in the port module itself."""

from __future__ import annotations

import ast
import inspect
from abc import ABC
from pathlib import Path

from orchestrator.domain.ports.container_runner_port import (
    ContainerRunnerPort,
    ResourceLimits,
    RunResult,
)

PORT_MODULE_PATH = (
    Path(__file__).parents[3]
    / "src"
    / "orchestrator"
    / "domain"
    / "ports"
    / "container_runner_port.py"
)


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_container_runner_port_module_never_imports_docker_sdk() -> None:
    source = PORT_MODULE_PATH.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    forbidden = {name for name in imported if name == "docker" or name.startswith("docker.")}
    assert forbidden == set(), f"domain port must not import the docker SDK, found: {forbidden}"


def test_container_runner_port_is_an_abc() -> None:
    assert issubclass(ContainerRunnerPort, ABC)


def test_container_runner_port_run_is_declared_sync_not_async() -> None:
    """Unlike every `ScanRunPort`/`ScanTaskPort` method, `.run()` is sync (D3)."""
    assert "run" in ContainerRunnerPort.__abstractmethods__
    assert not inspect.iscoroutinefunction(ContainerRunnerPort.run)


def test_resource_limits_is_frozen_and_slotted() -> None:
    limits = ResourceLimits(memory_mb=512, nano_cpus=1_000_000_000, pids_limit=128)
    assert limits.memory_mb == 512
    assert limits.nano_cpus == 1_000_000_000
    assert limits.pids_limit == 128
    assert not hasattr(limits, "__dict__")  # slots=True


def test_run_result_is_frozen_and_slotted() -> None:
    result = RunResult(exit_code=0, stdout="ok", stderr="", timed_out=False)
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.stderr == ""
    assert result.timed_out is False
    assert not hasattr(result, "__dict__")  # slots=True


def test_run_signature_appends_env_network_name_and_extra_tmpfs_in_order() -> None:
    """`env` (appended by an earlier PR4) plus `network_name`/`extra_tmpfs`
    (dast-scanner PR4, tasks 4.2/4.5) form the tail of the signature, in this
    exact append order — additive-only, so no existing caller needs to
    change. `env` is deliberately no longer required to be the absolute
    last parameter: later PRs append AFTER it, not before it."""
    params = list(inspect.signature(ContainerRunnerPort.run).parameters.values())
    tail = params[-3:]
    assert [p.name for p in tail] == ["env", "network_name", "extra_tmpfs"]
    for param in tail:
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert tail[0].default is None
    assert tail[1].default is None
    assert tail[2].default == ()
