"""`DockerContainerRunner` — mocked-SDK-client unit tests (Module 6 PR1, tasks 1.5-1.7).

Live-Docker proof that the hardening flags actually land on a real container
lives in `tests/integration/test_docker_container_runner_live.py` (task
1.12) — these tests only prove the SDK is invoked with the RIGHT arguments.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests.exceptions

from orchestrator.domain.ports.container_runner_port import ResourceLimits
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner

_LIMITS = ResourceLimits(memory_mb=512, nano_cpus=1_000_000_000, pids_limit=128)


def _make_mock_client(container: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    mock_container = container if container is not None else MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    client.containers.run.return_value = mock_container
    return client, mock_container


def test_run_launches_container_with_all_hardening_flags() -> None:
    client, container = _make_mock_client()
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-abc123",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    assert call_kwargs["user"] == "65532:65532"
    assert call_kwargs["read_only"] is True
    assert call_kwargs["cap_drop"] == ["ALL"]
    assert call_kwargs["security_opt"] == ["no-new-privileges"]
    assert call_kwargs["network_mode"] == "none"
    assert call_kwargs["mem_limit"] == "512m"
    assert call_kwargs["nano_cpus"] == 1_000_000_000
    assert call_kwargs["pids_limit"] == 128
    assert call_kwargs["detach"] is True
    assert "/tmp" in call_kwargs["tmpfs"]


def test_run_mounts_only_the_given_volume_read_only_when_requested() -> None:
    client, _container = _make_mock_client()
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-abc123",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    volumes = call_kwargs["volumes"]
    assert volumes == {"scan-abc123": {"bind": "/checkout", "mode": "ro"}}


def test_run_mounts_volume_read_write_when_read_only_mount_is_false() -> None:
    client, _container = _make_mock_client()
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="alpine/git:2.54.0",
        command=["clone", "--depth", "1", "https://example.com/x.git", "/workspace/checkout"],
        volume_name="scan-xyz789",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    assert call_kwargs["volumes"] == {"scan-xyz789": {"bind": "/workspace", "mode": "rw"}}
    assert call_kwargs["network_mode"] is None


def test_run_passes_command_as_argv_list_never_interpreted_as_shell() -> None:
    """A crafted ref/url containing shell metacharacters MUST reach the SDK
    verbatim as one list element — never string-concatenated into `sh -c`."""
    client, _container = _make_mock_client()
    runner = DockerContainerRunner(client=client)
    malicious_ref = "main; rm -rf / #"
    command = [
        "clone",
        "--branch",
        malicious_ref,
        "https://example.com/x.git",
        "/workspace/checkout",
    ]

    runner.run(
        image="alpine/git:2.54.0",
        command=command,
        volume_name="scan-1",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    assert call_kwargs["command"] == command
    assert isinstance(call_kwargs["command"], list)
    assert call_kwargs["command"][2] == malicious_ref  # untouched, not shell-interpreted


def test_run_never_passes_a_shell_string_command() -> None:
    client, _container = _make_mock_client()
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="alpine/git:2.54.0",
        command=["clone", "x"],
        volume_name="scan-1",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    assert not isinstance(call_kwargs["command"], str)


def test_run_returns_exit_code_and_captured_output_on_normal_completion() -> None:
    client, container = _make_mock_client()
    container.wait.return_value = {"StatusCode": 1}

    def _logs(*, stdout: bool, stderr: bool) -> bytes:
        if stdout:
            return b'{"leaks": []}'
        return b"warn: no config found"

    container.logs.side_effect = _logs
    runner = DockerContainerRunner(client=client)

    result = runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-1",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    assert result.exit_code == 1
    assert result.stdout == '{"leaks": []}'
    assert result.stderr == "warn: no config found"
    assert result.timed_out is False


def test_run_kills_and_reports_timeout_when_wait_exceeds_timeout_seconds() -> None:
    client, container = _make_mock_client()
    container.wait.side_effect = requests.exceptions.ReadTimeout("timed out")
    runner = DockerContainerRunner(client=client)

    result = runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-1",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=5,
    )

    assert result.timed_out is True
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_run_kills_and_reports_timeout_on_connection_error_wrapping_read_timeout() -> None:
    """Live-Docker discovery (task 1.12): depending on the `requests`/`urllib3`
    stack, a `.wait(timeout=...)` read-timeout sometimes surfaces as
    `requests.exceptions.ConnectionError` wrapping a
    `urllib3.exceptions.ReadTimeoutError` — NOT always a bare
    `requests.exceptions.ReadTimeout` (docker-py's own docstring undersells
    this) — confirmed empirically against a real daemon, not just inferred
    from source."""
    import urllib3.exceptions

    client, container = _make_mock_client()
    wrapped = requests.exceptions.ConnectionError(
        urllib3.exceptions.ReadTimeoutError(None, "/x", "timed out")
    )
    container.wait.side_effect = wrapped
    runner = DockerContainerRunner(client=client)

    result = runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-1",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=5,
    )

    assert result.timed_out is True
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_run_reraises_a_genuine_connection_error_not_wrapping_a_read_timeout() -> None:
    """A REAL connectivity failure (daemon unreachable, etc.) must NOT be
    misclassified as a timeout — it propagates so PR3 can map it to
    `TransientScanError` (D5), distinct from a deterministic timeout."""
    client, container = _make_mock_client()
    container.wait.side_effect = requests.exceptions.ConnectionError("daemon socket closed")
    runner = DockerContainerRunner(client=client)

    with pytest.raises(requests.exceptions.ConnectionError, match="daemon socket closed"):
        runner.run(
            image="ghcr.io/gitleaks/gitleaks:v8.30.1",
            command=["dir", "/checkout/checkout"],
            volume_name="scan-1",
            mount_path="/checkout",
            read_only_mount=True,
            network_disabled=True,
            limits=_LIMITS,
            timeout_seconds=5,
        )

    container.kill.assert_not_called()
    container.remove.assert_called_once_with(force=True)


@pytest.mark.parametrize("wait_raises", [False, True])
def test_run_always_force_removes_container_success_or_timeout(wait_raises: bool) -> None:
    client, container = _make_mock_client()
    if wait_raises:
        container.wait.side_effect = requests.exceptions.ReadTimeout("timed out")
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-1",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=5,
    )

    container.remove.assert_called_once_with(force=True)


def test_run_force_removes_container_even_when_logs_raise() -> None:
    client, container = _make_mock_client()
    container.logs.side_effect = RuntimeError("daemon connection dropped")
    runner = DockerContainerRunner(client=client)

    with pytest.raises(RuntimeError):
        runner.run(
            image="ghcr.io/gitleaks/gitleaks:v8.30.1",
            command=["dir", "/checkout/checkout"],
            volume_name="scan-1",
            mount_path="/checkout",
            read_only_mount=True,
            network_disabled=True,
            limits=_LIMITS,
            timeout_seconds=5,
        )

    container.remove.assert_called_once_with(force=True)


def test_run_never_mounts_the_docker_socket() -> None:
    """Threat Matrix: the socket lives in the worker process only, never a
    launched scanner/init container (task 1.7)."""
    client, _container = _make_mock_client()
    runner = DockerContainerRunner(client=client)

    runner.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-1",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    call_kwargs: dict[str, Any] = client.containers.run.call_args.kwargs
    volumes = call_kwargs["volumes"]
    assert "/var/run/docker.sock" not in volumes
    for mount in volumes.values():
        assert mount["bind"] != "/var/run/docker.sock"


def test_docker_container_runner_defaults_to_docker_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_client = MagicMock()
    monkeypatch.setattr(
        "orchestrator.infrastructure.container.docker_container_runner.docker.from_env",
        lambda: sentinel_client,
    )

    runner = DockerContainerRunner()

    assert runner._client is sentinel_client
