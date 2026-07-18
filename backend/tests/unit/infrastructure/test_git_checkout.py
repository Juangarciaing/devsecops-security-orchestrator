"""`GitCheckout` — shallow-clone via a short-lived init-container over a named
Docker volume (Module 6 D2, tasks 1.9-1.11).

`FakeContainerRunner` drives the two-argv-run clone+rev-parse behavior
without a real Docker socket; a `MagicMock` stands in for the low-level
`docker` client (volume create/get/remove only — never invoked via
`ContainerRunnerPort`, so it needs its own double)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError, GitCheckout
from tests.fakes.fake_container_runner import FakeContainerRunner

_CLONE_URL = "https://example.com/octocat/hello-world.git"
_REF = "main"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_checkout_runs_clone_then_rev_parse_as_two_argv_only_calls() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    settings = _settings()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=settings)

    ws = checkout.checkout(_CLONE_URL, _REF)

    assert len(fake_runner.calls) == 2
    clone_call, rev_parse_call = fake_runner.calls
    assert clone_call.command == [
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        _REF,
        _CLONE_URL,
        "/workspace/checkout",
    ]
    assert clone_call.image == settings.scan_git_image
    assert clone_call.read_only_mount is False
    assert clone_call.network_disabled is False
    assert clone_call.mount_path == "/workspace"

    assert rev_parse_call.command == ["-C", "/workspace/checkout", "rev-parse", "HEAD"]
    assert rev_parse_call.image == settings.scan_git_image
    assert rev_parse_call.volume_name == clone_call.volume_name

    assert ws.head_sha == "deadbeef1234"


def test_checkout_creates_named_volume_before_running_containers() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="abc\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    call_order: list[str] = []
    docker_client.volumes.create.side_effect = lambda **_: call_order.append("volume_create")
    docker_client.containers.run.side_effect = lambda **_: call_order.append("chmod_prep")
    original_run = fake_runner.run

    def _tracked_run(**kwargs: object) -> RunResult:
        call_order.append("container_run")
        return original_run(**kwargs)  # type: ignore[arg-type]

    fake_runner.run = _tracked_run  # type: ignore[method-assign]
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    ws = checkout.checkout(_CLONE_URL, _REF)

    docker_client.volumes.create.assert_called_once()
    created_name = docker_client.volumes.create.call_args.kwargs["name"]
    assert created_name.startswith("scan-")
    assert created_name == ws.volume_name
    assert call_order == ["volume_create", "chmod_prep", "container_run", "container_run"]


def test_checkout_chmods_the_fresh_volume_world_writable_before_the_nonroot_clone() -> None:
    """A freshly `docker.volumes.create()`d volume's mountpoint is root-owned
    on the host; without this world-writable prep step, the non-root
    (65532:65532) init-container the `ContainerRunnerPort` hardening
    contract mandates could never write its clone into it (discovered via
    the live-Docker proof, task 1.12 — not merely inferred from source)."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="abc\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    settings = _settings()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=settings)

    ws = checkout.checkout(_CLONE_URL, _REF)

    docker_client.containers.run.assert_called_once()
    prep_kwargs = docker_client.containers.run.call_args.kwargs
    assert prep_kwargs["image"] == settings.scan_git_image
    assert prep_kwargs["entrypoint"] == "chmod"
    assert prep_kwargs["command"] == ["0777", "/workspace"]
    assert prep_kwargs["volumes"] == {ws.volume_name: {"bind": "/workspace", "mode": "rw"}}
    assert prep_kwargs["remove"] is True
    # Never on the untrusted-network path and never inheriting the hardened
    # nonroot user — it MUST run as root (default) to chmod a root-owned dir.
    assert prep_kwargs["network_mode"] == "none"
    assert "user" not in prep_kwargs


def test_checkout_raises_checkout_failed_error_on_nonzero_clone_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="fatal: Remote branch bad-ref not found",
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="clone"):
        checkout.checkout(_CLONE_URL, "bad-ref")

    assert len(fake_runner.calls) == 1  # rev-parse never attempted after a failed clone


def test_checkout_raises_checkout_failed_error_on_nonzero_rev_parse_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=128, stdout="", stderr="fatal: not a git repository", timed_out=False),
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="rev-parse"):
        checkout.checkout(_CLONE_URL, _REF)


def test_checkout_removes_volume_when_clone_fails() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=128, stdout="", stderr="fatal: bad ref", timed_out=False)
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError):
        checkout.checkout(_CLONE_URL, "bad-ref")

    created_name = docker_client.volumes.create.call_args.kwargs["name"]
    docker_client.volumes.get.assert_called_once_with(created_name)
    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)


def test_checkout_removes_volume_and_reraises_when_runner_raises_unexpectedly() -> None:
    fake_runner = FakeContainerRunner()

    def _raise(**_: object) -> RunResult:
        raise RuntimeError("docker daemon unreachable")

    fake_runner.run = _raise  # type: ignore[method-assign]
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(RuntimeError, match="docker daemon unreachable"):
        checkout.checkout(_CLONE_URL, _REF)

    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)


def test_workspace_context_manager_removes_volume_on_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="sha\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())
    ws = checkout.checkout(_CLONE_URL, _REF)
    docker_client.volumes.get.reset_mock()  # only the deferred exit-time removal should count here

    with ws as entered:
        assert entered is ws

    docker_client.volumes.get.assert_called_once_with(ws.volume_name)
    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)
