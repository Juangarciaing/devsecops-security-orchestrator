"""Live-Docker end-to-end proof for the DAST scanner slice (dast-scanner
design D3/D4/D6/D7, PR5, task 5.15) — REAL Docker socket, REAL
`ZapDastDockerExecution`, REAL `DockerContainerRunner`, REAL locally-built
`zap-scanner:local` image, REAL disposable HTTP target container. No mocks
anywhere in the executed pipeline.

Mirrors `test_pip_audit_adapter_live.py`/`test_semgrep_adapter_live.py`'s
structure: a `docker_client` fixture that skips when no Docker socket is
reachable, a `_settings()` helper building a real `Settings` object, and a
real `DockerContainerRunner(client=docker_client)`.

## Honest, documented limitation: the SSRF guard is bypassed for THIS file only

`ZapDastDockerExecution.execute()` calls `dns_target_resolver
.resolve_and_authorize()` immediately before its first `runner.run()`
(design D3). That guard fail-closed-rejects EVERY private, loopback,
link-local, and reserved IP range (`is_blocked_ip`, design D3's full CIDR
table) — which by construction includes every address a disposable local
Docker container can ever have, whether on the default bridge, a
compose-managed network, or the dedicated `dast` network itself (all of
which live inside `172.16.0.0/12`, one of the explicitly blocked ranges).
There is no way to point the REAL, unmodified guard at a REAL local
container without either (a) exposing this machine's Docker daemon to a
genuine public IP (unsafe, non-reproducible, out of scope) or (b) bypassing
just that DNS-blocklist check for this test's disposable target, exactly as
`test_zap_dast_execution.py`'s own `_patch_guard` unit-test helper already
does. That guard's full blocked-CIDR matrix (15 literal-IP cases + 3
resolving-hostname cases) is already exhaustively proven in
`test_zap_dast_execution.py` at the unit level — re-proving it here would be
redundant, not more real. This file's job is different and complementary:
prove the REST of the pipeline (network creation, volume lifecycle, the
real ZAP container, real report parsing, real cleanup, and the REAL Docker
network isolation guarantee) against a REAL Docker daemon, which no unit
test (mocked `docker_client`/`ContainerRunnerPort`) can prove.

`validate_target_url_shape` (the non-DNS half of the guard) is NOT
bypassed — the target URL still has to be a well-formed `http(s)://<host>/`
URL with no userinfo, matching production shape rules exactly.

Skips automatically if no Docker socket is reachable, matching this repo's
other live-scanner integration tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import docker
import pytest

from orchestrator.domain.ports.target_scan_execution_port import TargetScanExecutionResult
from orchestrator.domain.services.target_url_policy import validate_target_url_shape
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container import zap_dast_execution
from orchestrator.infrastructure.container.dast_network import ensure_dast_network
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.container.zap_dast_execution import ZapDastDockerExecution

pytestmark = pytest.mark.integration

_ISOLATION_TIMEOUT_SECONDS = 2


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


def _bypass_dns_blocklist_but_keep_real_shape_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real `validate_target_url_shape` still runs; only the DNS-resolution
    blocklist half of the guard is skipped, for the documented reason in
    this module's docstring."""

    async def _fake_resolve_and_authorize(url: str) -> str:
        validate_target_url_shape(url)
        return url

    monkeypatch.setattr(zap_dast_execution, "resolve_and_authorize", _fake_resolve_and_authorize)


def _compose_container_ip(docker_client: docker.DockerClient, service: str) -> tuple[str, str]:
    """Find the live compose-managed container for `service` via the
    standard `com.docker.compose.service` label (project-name independent)
    and return `(network_name, ip_address)` off its FIRST attached network."""
    containers = docker_client.containers.list(
        filters={"label": f"com.docker.compose.service={service}"}
    )
    assert containers, (
        f"no running compose container found for service {service!r} — "
        "expected `docker compose up -d postgres redis` to already be up"
    )
    networks = containers[0].attrs["NetworkSettings"]["Networks"]
    network_name, network_info = next(iter(networks.items()))
    return network_name, network_info["IPAddress"]


def test_zap_scan_completes_end_to_end_against_a_disposable_target_and_is_network_isolated(
    docker_client: docker.DockerClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    _bypass_dns_blocklist_but_keep_real_shape_validation(monkeypatch)

    network_name = ensure_dast_network(docker_client, settings)

    target_name = f"dast-live-target-{uuid.uuid4().hex[:8]}"
    target_container = docker_client.containers.run(
        image="nginx:1.27-alpine",
        name=target_name,
        network=network_name,
        detach=True,
        remove=False,
    )

    try:
        target_container.reload()
        assert target_container.status in {"running", "created"}

        target_url = f"http://{target_name}/"
        runner = DockerContainerRunner(client=docker_client)
        execution = ZapDastDockerExecution(runner, docker_client, settings)
        scan_task_id = uuid.uuid4()

        result = execution.execute(target_url, scan_task_id, ScannerType.DAST)

        # --- pipeline shape assertions -----------------------------------
        assert isinstance(result, TargetScanExecutionResult)
        assert isinstance(result.findings, list)
        for finding in result.findings:
            assert finding.scan_task_id == scan_task_id
            assert finding.rule_id
            assert finding.title
        print(
            f"\n[test_zap_dast_execution_live] real ZAP baseline scan against "
            f"a disposable nginx:1.27-alpine target returned "
            f"{len(result.findings)} finding(s)."
        )

        # The ZAP container itself must have been force-removed by the
        # runner (same "no leaked scanner containers" contract every other
        # live-scanner test asserts).
        remaining = docker_client.containers.list(
            all=True, filters={"ancestor": settings.scan_zap_image}
        )
        assert remaining == [], "ZAP scanner container was not force-removed after completion"

        # --- network isolation assertion (design D4) ----------------------
        # A throwaway container attached to the SAME `dast` network the ZAP
        # scan itself just joined must NOT be able to reach this project's
        # live compose `postgres`/`redis` services, by hostname OR by IP,
        # bounded by a short timeout so this can never hang.
        _SERVICE_PORTS = {"postgres": 5432, "redis": 6379}
        for service, port in _SERVICE_PORTS.items():
            compose_network, compose_ip = _compose_container_ip(docker_client, service)
            assert compose_network != network_name, (
                f"{service} and the dast network must never be the same network"
            )

            probe_script = (
                f"nc -z -w {_ISOLATION_TIMEOUT_SECONDS} {service} {port} 2>/dev/null; "
                "echo BY_NAME:$?; "
                f"nc -z -w {_ISOLATION_TIMEOUT_SECONDS} {compose_ip} {port} 2>/dev/null; "
                "echo BY_IP:$?"
            )
            probe_output = docker_client.containers.run(
                image="alpine:3.22",
                network=network_name,
                command=["sh", "-c", probe_script],
                remove=True,
            ).decode("utf-8")

            assert "BY_NAME:0" not in probe_output, (
                f"a container on the dast network reached {service!r} BY NAME "
                f"— network isolation is broken (output: {probe_output!r})"
            )
            assert "BY_IP:0" not in probe_output, (
                f"a container on the dast network reached {service!r}'s "
                f"compose IP {compose_ip} — network isolation is broken "
                f"(output: {probe_output!r})"
            )
    finally:
        target_container.remove(force=True)
