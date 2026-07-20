"""Live-Docker proof for Module 11 PR2 (pip-audit adapter) — REAL Docker
socket, REAL locally-built pip-audit image (`docker/pip-audit.Dockerfile`),
no mocks.

Confirms, against a REAL daemon, that `PipAuditAdapter.scan()` + `parse()`:
1. detect a REAL, currently-known vulnerability (`requests==2.19.0`,
   PYSEC-2018-28 / CVE-2018-18074 — confirmed via the REAL pip-audit output
   below, not assumed) via the network-enabled scan path;
2. report zero findings for a clean, unpinned-vulnerability manifest
   (`requests==2.32.3`);
3. report zero findings (success, NOT a failure) when no `requirements.txt`
   is present at all (the D3 probe short-circuit).

Mirrors `test_gitleaks_adapter_live.py`'s fixture-volume technique (a
throwaway root container against `settings.scan_git_image`, bypassing
`GitCheckout` — checkout -> scan wiring is proven separately via the live
HTTP API e2e run, tracked in apply-progress, not this file's scope).

Skips automatically if no Docker socket is reachable, matching
`test_docker_container_runner_live.py`/`test_gitleaks_adapter_live.py`'s
pattern.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import docker
import pytest

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.scanners.pip_audit_adapter import (
    DEFAULT_SEVERITY,
    PipAuditAdapter,
)

pytestmark = pytest.mark.integration


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


def _prepare_fixture_volume(
    client: docker.DockerClient,
    volume_name: str,
    settings: Settings,
    *,
    requirements_content: str | None,
) -> None:
    """Create `volume_name` and write a `checkout/` subdir into it directly
    (bypassing `GitCheckout` — this file proves the pip-audit adapter in
    isolation, mirroring `test_gitleaks_adapter_live.py`).

    `requirements_content=None` -> no `requirements.txt` at all (D3's
    no-manifest probe scenario).
    """
    client.volumes.create(name=volume_name)
    if requirements_content is None:
        script = "mkdir -p /checkout/checkout"
    else:
        script = (
            "mkdir -p /checkout/checkout && "
            f'printf "{requirements_content}" > /checkout/checkout/requirements.txt'
        )
    client.containers.run(
        image=settings.scan_git_image,
        entrypoint="sh",
        command=["-c", script],
        volumes={volume_name: {"bind": "/checkout", "mode": "rw"}},
        network_mode="none",
        remove=True,
    )


def test_pip_audit_adapter_detects_a_real_known_vulnerability_via_real_docker(
    docker_client: docker.DockerClient,
) -> None:
    settings = _settings()
    volume_name = f"scan-live-pip-audit-{uuid.uuid4().hex}"
    _prepare_fixture_volume(
        docker_client, volume_name, settings, requirements_content="requests==2.19.0\n"
    )

    try:
        runner = DockerContainerRunner(client=docker_client)
        adapter = PipAuditAdapter(runner=runner, settings=settings)

        result = adapter.scan(volume_name)
        assert result.timed_out is False

        scan_task_id = uuid.uuid4()
        findings = adapter.parse(result, scan_task_id)

        assert len(findings) >= 1
        finding = findings[0]
        assert finding.scan_task_id == scan_task_id
        assert finding.severity == DEFAULT_SEVERITY
        # Real pip-audit 2.10.1 output for requests==2.19.0 (captured
        # directly, not assumed): `id="PYSEC-2018-28"`, aliases
        # `["GHSA-x84v-xcm2-53pg", "CVE-2018-18074"]`, fix_versions
        # `["2.20.0"]` — the CVE-2018-18074 auth-header-leak-on-redirect bug.
        assert any(f.rule_id == "PYSEC-2018-28" for f in findings)
        assert "requests" in finding.title
        assert finding.file_path == "requirements.txt"
        assert finding.fingerprint
    finally:
        docker_client.volumes.get(volume_name).remove(force=True)

    remaining = docker_client.containers.list(
        all=True, filters={"ancestor": settings.scan_pip_audit_image}
    )
    assert remaining == [], "pip-audit container was not force-removed after completion"


def test_pip_audit_adapter_reports_zero_findings_on_a_real_clean_manifest(
    docker_client: docker.DockerClient,
) -> None:
    settings = _settings()
    volume_name = f"scan-live-pip-audit-clean-{uuid.uuid4().hex}"
    _prepare_fixture_volume(
        docker_client, volume_name, settings, requirements_content="requests==2.34.2\n"
    )

    try:
        runner = DockerContainerRunner(client=docker_client)
        adapter = PipAuditAdapter(runner=runner, settings=settings)

        result = adapter.scan(volume_name)
        assert result.timed_out is False

        findings = adapter.parse(result, uuid.uuid4())
        assert findings == []
    finally:
        docker_client.volumes.get(volume_name).remove(force=True)


def test_pip_audit_adapter_reports_zero_findings_when_no_manifest_present(
    docker_client: docker.DockerClient,
) -> None:
    """D3 probe short-circuit against the REAL image — no `requirements.txt`
    at all must complete as a successful, zero-finding scan, never a
    `PipAuditFailedError`, and must never launch the network-enabled
    container for a guaranteed no-op."""
    settings = _settings()
    volume_name = f"scan-live-pip-audit-no-manifest-{uuid.uuid4().hex}"
    _prepare_fixture_volume(docker_client, volume_name, settings, requirements_content=None)

    try:
        runner = DockerContainerRunner(client=docker_client)
        adapter = PipAuditAdapter(runner=runner, settings=settings)

        result = adapter.scan(volume_name)
        assert result.timed_out is False

        findings = adapter.parse(result, uuid.uuid4())
        assert findings == []
    finally:
        docker_client.volumes.get(volume_name).remove(force=True)
