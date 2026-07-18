"""Live-Docker proof for Module 6 PR1 (task 1.12) — REAL Docker socket, no mocks.

Confirms, against a REAL daemon:
- the named-volume sibling-container handoff pattern actually works
  (`GitCheckout` clone + rev-parse against a real public repo)
- `docker inspect` on the ACTUALLY RUNNING container shows every hardening
  flag was genuinely applied (not merely asserted against a mock)
- a deliberately-triggered timeout genuinely SIGKILLs the container
- cleanup (container + volume removal) genuinely happens in every case

Skips automatically if no Docker socket is reachable (`client.ping()`
fails) — CI/unit runs elsewhere in the suite don't need Docker.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import docker
import docker.errors
import pytest

from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError, GitCheckout

pytestmark = pytest.mark.integration

_TRIVIAL_IMAGE = "alpine:latest"
_LIMITS = ResourceLimits(memory_mb=512, nano_cpus=1_000_000_000, pids_limit=128)
_PUBLIC_REPO_URL = "https://github.com/octocat/Hello-World.git"
_PUBLIC_REPO_REF = "master"


def _live_docker_client() -> docker.DockerClient:
    client = docker.from_env()
    client.ping()
    return client


@pytest.fixture
def docker_client() -> Iterator[docker.DockerClient]:
    try:
        client = _live_docker_client()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no reachable Docker socket: {exc}")
    yield client
    client.close()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def _poll_running_container_by_image(
    client: docker.DockerClient, image: str, timeout: float = 10.0
) -> dict[str, object]:
    """Poll `docker ps` for a running container of `image`, return its `docker inspect` attrs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = client.containers.list(filters={"ancestor": image, "status": "running"})
        if candidates:
            return dict(client.api.inspect_container(candidates[0].id))
        time.sleep(0.1)
    raise AssertionError(f"no running container for image {image!r} observed within {timeout}s")


def test_run_hardening_flags_are_genuinely_applied_on_a_real_running_container(
    docker_client: docker.DockerClient,
) -> None:
    volume = docker_client.volumes.create(name="scan-live-hardening-test")
    runner = DockerContainerRunner(client=docker_client)
    result_holder: dict[str, RunResult] = {}

    def _run() -> None:
        result_holder["result"] = runner.run(
            image=_TRIVIAL_IMAGE,
            command=["sleep", "4"],
            volume_name=volume.name,
            mount_path="/checkout",
            read_only_mount=True,
            network_disabled=True,
            limits=_LIMITS,
            timeout_seconds=30,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    try:
        attrs = _poll_running_container_by_image(docker_client, _TRIVIAL_IMAGE)
        host_config = attrs["HostConfig"]
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["NetworkMode"] == "none"
        assert host_config["CapDrop"] == ["ALL"]
        assert host_config["PidsLimit"] == 128
        assert host_config["Memory"] == 512 * 1024 * 1024
        assert attrs["Config"]["User"] == "65532:65532"
        mounts = attrs["Mounts"]
        assert len(mounts) == 1
        assert mounts[0]["Name"] == volume.name
        assert mounts[0]["Destination"] == "/checkout"
        assert mounts[0]["RW"] is False
    finally:
        thread.join(timeout=30)

    result = result_holder["result"]
    assert result.exit_code == 0
    assert result.timed_out is False

    remaining = docker_client.containers.list(all=True, filters={"ancestor": _TRIVIAL_IMAGE})
    assert remaining == [], "container was not force-removed after completion"

    docker_client.volumes.get(volume.name).remove(force=True)


def test_run_sigkills_and_cleans_up_a_container_that_exceeds_the_timeout(
    docker_client: docker.DockerClient,
) -> None:
    volume = docker_client.volumes.create(name="scan-live-timeout-test")
    runner = DockerContainerRunner(client=docker_client)

    started = time.monotonic()
    result = runner.run(
        image=_TRIVIAL_IMAGE,
        command=["sleep", "60"],
        volume_name=volume.name,
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=2,
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    # Genuinely SIGKILLed well before the 60s sleep would naturally finish.
    assert elapsed < 20, (
        f"expected a fast SIGKILL, took {elapsed:.1f}s (sleep 60 never interrupted?)"
    )

    remaining = docker_client.containers.list(all=True, filters={"ancestor": _TRIVIAL_IMAGE})
    assert remaining == [], "container was not force-removed after timeout"

    docker_client.volumes.get(volume.name).remove(force=True)


def test_git_checkout_named_volume_sibling_handoff_against_a_real_public_repo(
    docker_client: docker.DockerClient,
) -> None:
    """Proves D1/D2 for real: the init-container clones into a named volume
    that this test (a THIRD, independent process) can also see/inspect —
    exactly the sibling-container visibility a bind-mount could not give."""
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=_settings())

    ws = checkout.checkout(_PUBLIC_REPO_URL, _PUBLIC_REPO_REF)
    try:
        assert len(ws.head_sha) == 40
        assert all(c in "0123456789abcdef" for c in ws.head_sha)

        # Independently confirm the volume is real and populated — inspect it
        # via a fresh throwaway container, sibling to the one that cloned it.
        docker_client.volumes.get(ws.volume_name)  # raises NotFound if absent
        verify_output = docker_client.containers.run(
            image=_TRIVIAL_IMAGE,
            command=["test", "-f", "/checkout/checkout/README"],
            volumes={ws.volume_name: {"bind": "/checkout", "mode": "ro"}},
            remove=True,
        )
        assert verify_output == b""  # `test` prints nothing on success, exit 0
    finally:
        with ws:
            pass  # deferred volume cleanup (Workspace.__exit__)

    with pytest.raises(docker.errors.NotFound):
        docker_client.volumes.get(ws.volume_name)


def test_git_checkout_cleans_up_volume_on_a_real_bad_ref_failure(
    docker_client: docker.DockerClient,
) -> None:
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError):
        checkout.checkout(_PUBLIC_REPO_URL, "this-branch-does-not-exist-anywhere")

    remaining_volumes = [v.name for v in docker_client.volumes.list() if v.name.startswith("scan-")]
    assert remaining_volumes == [], f"orphaned scan volumes left behind: {remaining_volumes}"
