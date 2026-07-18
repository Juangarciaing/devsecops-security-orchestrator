"""`FakeContainerRunner` — the in-memory `ContainerRunnerPort` test double other
modules' unit tests script against (no Docker socket needed)."""

from __future__ import annotations

from orchestrator.domain.ports.container_runner_port import ResourceLimits, RunResult
from tests.fakes.fake_container_runner import FakeContainerRunner

_LIMITS = ResourceLimits(memory_mb=512, nano_cpus=1_000_000_000, pids_limit=128)


def test_fake_container_runner_records_call_kwargs() -> None:
    fake = FakeContainerRunner()

    fake.run(
        image="alpine/git:2.54.0",
        command=["clone", "--depth", "1", "https://example.com/repo.git", "/workspace/checkout"],
        volume_name="scan-abc123",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    assert len(fake.calls) == 1
    recorded = fake.calls[0]
    assert recorded.image == "alpine/git:2.54.0"
    assert recorded.command == [
        "clone",
        "--depth",
        "1",
        "https://example.com/repo.git",
        "/workspace/checkout",
    ]
    assert recorded.volume_name == "scan-abc123"
    assert recorded.mount_path == "/workspace"
    assert recorded.read_only_mount is False
    assert recorded.network_disabled is False
    assert recorded.limits == _LIMITS
    assert recorded.timeout_seconds == 120


def test_fake_container_runner_returns_scripted_results_in_order() -> None:
    fake = FakeContainerRunner()
    first = RunResult(exit_code=0, stdout="run-1-stdout", stderr="", timed_out=False)
    second = RunResult(exit_code=0, stdout="deadbeef", stderr="", timed_out=False)
    fake.script(first, second)

    result_1 = fake.run(
        image="alpine/git:2.54.0",
        command=["clone"],
        volume_name="scan-1",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )
    result_2 = fake.run(
        image="alpine/git:2.54.0",
        command=["rev-parse", "HEAD"],
        volume_name="scan-1",
        mount_path="/workspace",
        read_only_mount=False,
        network_disabled=False,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    assert result_1 is first
    assert result_2 is second
    assert len(fake.calls) == 2


def test_fake_container_runner_defaults_to_a_successful_result_when_unscripted() -> None:
    fake = FakeContainerRunner()

    result = fake.run(
        image="ghcr.io/gitleaks/gitleaks:v8.30.1",
        command=["dir", "/checkout/checkout"],
        volume_name="scan-2",
        mount_path="/checkout",
        read_only_mount=True,
        network_disabled=True,
        limits=_LIMITS,
        timeout_seconds=120,
    )

    assert result.exit_code == 0
    assert result.timed_out is False
