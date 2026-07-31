"""`ZapDastDockerExecution` — guard -> network -> volume -> 2 runs -> parse ->
cleanup wiring for a DAST target-subject scan (dast-scanner design D3/D4/D6/D7,
PR5b-ii, tasks 5.2-5.7).

Threat matrix covered here (dast-scanner design, PR5b-ii slice):
- command composition: a shell-metacharacter payload is either rejected by
  shape validation before any container/network call, or passes through as
  ONE opaque argv element — never shell-interpreted.
- network egress / SSRF: every representative PR3-blocked address (literal
  IP and resolving hostname) is rejected with ZERO `runner.run()` and ZERO
  `ensure_dast_network()`/`docker_client.networks.create()` calls.
- secret-to-subprocess channel: run 1's `env` carries exactly `{"HOME":
  "/zap/wrk"}`, nothing else (folded into the execution-order test).
- container hardening drift: run 1's `user`/`extra_tmpfs` overrides vs run
  2's plain (default-hardened) invocation (folded into the execution-order
  test).
- backend divergence: `create_target_scan_execution` routing is covered in
  `test_scan_execution_factory.py`, not here.
"""

from __future__ import annotations

import json
import socket
import uuid
from unittest.mock import MagicMock

import pytest

from orchestrator.domain.ports.container_runner_port import RunResult, TmpfsMount
from orchestrator.domain.services.target_url_policy import (
    InvalidTargetUrlError,
    validate_target_url_shape,
)
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container import zap_dast_execution
from orchestrator.infrastructure.container.zap_dast_execution import ZapDastDockerExecution
from orchestrator.infrastructure.security.dns_target_resolver import (
    TargetResolutionError,
    resolve_and_authorize,
)
from tests.fakes.fake_container_runner import FakeContainerRunner

_TARGET_URL = "https://target.example/"
_ZERO_ALERT_REPORT = json.dumps({"site": []})


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def _tracked_docker_client(call_order: list[str]) -> MagicMock:
    docker_client = MagicMock()
    docker_client.volumes.create.side_effect = lambda **_: call_order.append("volume_create")
    docker_client.containers.run.side_effect = lambda **_: call_order.append("chmod_prep")
    docker_client.volumes.get.return_value.remove.side_effect = lambda **_: call_order.append(
        "volume_cleanup"
    )
    return docker_client


def _tracked_runner(call_order: list[str], *results: RunResult) -> FakeContainerRunner:
    runner = FakeContainerRunner()
    runner.script(*results)
    original_run = runner.run

    def _tracked(**kwargs: object) -> RunResult:
        call_order.append("container_run")
        return original_run(**kwargs)  # type: ignore[arg-type]

    runner.run = _tracked  # type: ignore[method-assign]
    return runner


def _patch_guard(monkeypatch: pytest.MonkeyPatch, call_order: list[str]) -> None:
    """Bypass real DNS resolution (no live network in unit tests) while
    still exercising the REAL shape guard — proves shape-valid-but-shell-
    dangerous payloads are not rejected by shape validation alone."""

    async def _fake_resolve_and_authorize(url: str) -> str:
        validate_target_url_shape(url)
        call_order.append("resolve_and_authorize")
        return url

    monkeypatch.setattr(zap_dast_execution, "resolve_and_authorize", _fake_resolve_and_authorize)

    def _fake_ensure_dast_network(docker_client: object, settings: object) -> str:
        call_order.append("ensure_dast_network")
        return "dast-scan-net"

    monkeypatch.setattr(zap_dast_execution, "ensure_dast_network", _fake_ensure_dast_network)


# ---------------------------------------------------------------------------
# 5.2 — execution order (+ 5.5 secret channel, 5.6 hardening drift, folded in)
# ---------------------------------------------------------------------------


def test_execute_runs_guard_network_volume_run1_run2_parse_cleanup_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []
    _patch_guard(monkeypatch, call_order)
    docker_client = _tracked_docker_client(call_order)
    runner = _tracked_runner(
        call_order,
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout=_ZERO_ALERT_REPORT, stderr="", timed_out=False),
    )
    execution = ZapDastDockerExecution(runner, docker_client, _settings())
    scan_task_id = uuid.uuid4()

    result = execution.execute(_TARGET_URL, scan_task_id, ScannerType.DAST)

    assert call_order == [
        "resolve_and_authorize",
        "ensure_dast_network",
        "volume_create",
        "chmod_prep",
        "container_run",
        "container_run",
        "volume_cleanup",
    ]
    assert result.findings == []

    run1, run2 = runner.calls
    assert run1.image == "zap-scanner:local"
    assert run1.command == [
        "zap-baseline.py",
        "-t",
        _TARGET_URL,
        "-J",
        "report.json",
        "-I",
        "-s",
    ]
    assert run1.network_name == "dast-scan-net"
    assert run1.network_disabled is False
    assert run1.mount_path == "/zap/wrk"
    assert run1.read_only_mount is False
    assert run1.volume_name == run2.volume_name

    # 5.5 — secret-to-subprocess channel: exactly HOME, nothing else.
    assert run1.env == {"HOME": "/zap/wrk"}

    # 5.6 — container hardening drift: run 1's override vs run 2's defaults.
    assert run1.user == "1000:1000"
    assert run1.extra_tmpfs == (TmpfsMount("/home/zap", uid=1000, gid=1000, size_mb=512),)

    assert run2.command == ["cat", "/zap/wrk/report.json"]
    assert run2.network_disabled is True
    assert run2.read_only_mount is True
    assert run2.user is None
    assert run2.extra_tmpfs == ()
    assert run2.env is None


def test_execute_creates_a_fresh_volume_and_chmods_it_before_run1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []
    _patch_guard(monkeypatch, call_order)
    docker_client = _tracked_docker_client(call_order)
    runner = _tracked_runner(
        call_order,
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout=_ZERO_ALERT_REPORT, stderr="", timed_out=False),
    )
    execution = ZapDastDockerExecution(runner, docker_client, _settings())

    execution.execute(_TARGET_URL, uuid.uuid4(), ScannerType.DAST)

    docker_client.volumes.create.assert_called_once()
    created_name = docker_client.volumes.create.call_args.kwargs["name"]
    assert created_name.startswith("dast-")
    prep_kwargs = docker_client.containers.run.call_args.kwargs
    assert prep_kwargs["entrypoint"] == "chmod"
    assert prep_kwargs["command"] == ["0777", "/zap/wrk"]
    assert prep_kwargs["network_mode"] == "none"
    assert "user" not in prep_kwargs
    docker_client.volumes.get.assert_called_once_with(created_name)


def test_execute_propagates_guard_rejection_before_any_network_or_volume_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _always_rejects(url: str) -> str:
        raise TargetResolutionError("resolved address is blocked")

    monkeypatch.setattr(zap_dast_execution, "resolve_and_authorize", _always_rejects)
    docker_client = MagicMock()
    runner = FakeContainerRunner()
    execution = ZapDastDockerExecution(runner, docker_client, _settings())

    with pytest.raises(TargetResolutionError):
        execution.execute(_TARGET_URL, uuid.uuid4(), ScannerType.DAST)

    assert runner.calls == []
    docker_client.volumes.create.assert_not_called()
    docker_client.networks.create.assert_not_called()


# ---------------------------------------------------------------------------
# 5.4 — network egress / SSRF: every representative PR3-blocked address
# ---------------------------------------------------------------------------

_BLOCKED_IP_LITERAL_URLS = [
    "http://0.0.0.0/",
    "http://10.0.0.1/",
    "http://100.64.0.1/",
    "http://127.0.0.1/",
    "http://169.254.169.254/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://198.18.0.1/",
    "http://224.0.0.1/",
    "http://240.0.0.1/",
    "https://[::1]/",
    "https://[fc00::1]/",
    "https://[fe80::1]/",
    "https://[ff00::1]/",
    "https://[64:ff9b::1]/",
]


@pytest.mark.parametrize("blocked_url", _BLOCKED_IP_LITERAL_URLS)
def test_execute_rejects_every_blocked_literal_ip_with_zero_container_or_network_calls(
    blocked_url: str,
) -> None:
    docker_client = MagicMock()
    runner = FakeContainerRunner()
    execution = ZapDastDockerExecution(runner, docker_client, _settings())

    with pytest.raises(InvalidTargetUrlError):
        execution.execute(blocked_url, uuid.uuid4(), ScannerType.DAST)

    assert runner.calls == []
    docker_client.volumes.create.assert_not_called()
    docker_client.networks.create.assert_not_called()


_BLOCKED_RESOLVING_HOSTNAME_CASES = [
    ("internal.example", "127.0.0.1"),
    ("metadata.internal.example", "169.254.169.254"),
    ("ula.internal.example", "fc00::1"),
]


@pytest.mark.parametrize(("hostname", "blocked_ip"), _BLOCKED_RESOLVING_HOSTNAME_CASES)
def test_execute_rejects_a_hostname_resolving_to_a_blocked_address_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch, hostname: str, blocked_ip: str
) -> None:
    def _fake_getaddrinfo(host: str, port: object) -> list:
        assert host == hostname
        family = socket.AF_INET6 if ":" in blocked_ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (blocked_ip, 0))]

    async def _resolve_via_fake(url: str) -> str:
        return await resolve_and_authorize(url, resolver=_fake_getaddrinfo)

    monkeypatch.setattr(zap_dast_execution, "resolve_and_authorize", _resolve_via_fake)
    docker_client = MagicMock()
    runner = FakeContainerRunner()
    execution = ZapDastDockerExecution(runner, docker_client, _settings())

    with pytest.raises(TargetResolutionError):
        execution.execute(f"https://{hostname}/", uuid.uuid4(), ScannerType.DAST)

    assert runner.calls == []
    docker_client.volumes.create.assert_not_called()
    docker_client.networks.create.assert_not_called()


# ---------------------------------------------------------------------------
# 5.3 — command composition: never a shell string
# ---------------------------------------------------------------------------

_COMMAND_INJECTION_PAYLOADS = [
    "; rm -rf /",
    "$(id)",
    "--config=/etc/passwd",
    "-rf",
]


@pytest.mark.parametrize("payload", _COMMAND_INJECTION_PAYLOADS)
def test_execute_rejects_a_shell_metacharacter_payload_used_as_the_whole_url(
    payload: str,
) -> None:
    """None of these bare payloads are a well-formed http(s) URL shape at
    all — rejected before any container/network call, never reaching
    `build_zap_argv`."""
    docker_client = MagicMock()
    runner = FakeContainerRunner()
    execution = ZapDastDockerExecution(runner, docker_client, _settings())

    with pytest.raises(InvalidTargetUrlError):
        execution.execute(payload, uuid.uuid4(), ScannerType.DAST)

    assert runner.calls == []


@pytest.mark.parametrize("payload", _COMMAND_INJECTION_PAYLOADS)
def test_execute_passes_a_shape_valid_url_with_metacharacters_as_one_opaque_argv_element(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """A metacharacter payload embedded in an otherwise shape-valid URL's
    path passes shape validation and is placed as ONE opaque argv element
    after `-t` — never shell-interpreted, never split into extra tokens."""
    call_order: list[str] = []
    _patch_guard(monkeypatch, call_order)
    docker_client = _tracked_docker_client(call_order)
    runner = _tracked_runner(
        call_order,
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout=_ZERO_ALERT_REPORT, stderr="", timed_out=False),
    )
    execution = ZapDastDockerExecution(runner, docker_client, _settings())
    malicious_url = f"https://target.example/{payload}"

    execution.execute(malicious_url, uuid.uuid4(), ScannerType.DAST)

    run1 = runner.calls[0]
    assert run1.command == [
        "zap-baseline.py",
        "-t",
        malicious_url,
        "-J",
        "report.json",
        "-I",
        "-s",
    ]
    assert run1.command.count(malicious_url) == 1
    assert len(run1.command) == 7
