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
    TmpfsMount,
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


def test_run_signature_appends_env_network_name_extra_tmpfs_and_user_in_order() -> None:
    """`env` (appended by an earlier PR4) plus `network_name`/`extra_tmpfs`
    (dast-scanner PR4, tasks 4.2/4.5) and `user` (dast-scanner PR5b, design
    D6 rung 3) form the tail of the signature, in this exact append order —
    additive-only, so no existing caller needs to change. `env` is
    deliberately no longer required to be the absolute last parameter: later
    PRs append AFTER it, not before it."""
    params = list(inspect.signature(ContainerRunnerPort.run).parameters.values())
    tail = params[-4:]
    assert [p.name for p in tail] == ["env", "network_name", "extra_tmpfs", "user"]
    for param in tail:
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert tail[0].default is None
    assert tail[1].default is None
    assert tail[2].default == ()
    assert tail[3].default is None


def test_tmpfs_mount_is_frozen_and_slotted_with_optional_fields_defaulted_none() -> None:
    """`TmpfsMount` (dast-scanner PR5b) replaces the bare-path-string shape
    of `extra_tmpfs` with one that can express per-path uid/gid/size mount
    options — required for ZAP's `/home/zap` tmpfs (PR4 spike: rung 1/2
    fail, rung 3 needs `uid=1000,gid=1000,size>=512m`). Every field beyond
    `path` defaults to `None`, reproducing a bare path's behavior."""
    mount = TmpfsMount(path="/home/zap")
    assert mount.path == "/home/zap"
    assert mount.uid is None
    assert mount.gid is None
    assert mount.size_mb is None
    assert not hasattr(mount, "__dict__")  # slots=True

    sized = TmpfsMount(path="/home/zap", uid=1000, gid=1000, size_mb=512)
    assert sized.uid == 1000
    assert sized.gid == 1000
    assert sized.size_mb == 512
