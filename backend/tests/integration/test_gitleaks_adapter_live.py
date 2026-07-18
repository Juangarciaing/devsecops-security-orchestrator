"""Live-Docker proof for Module 6 PR2 (Gitleaks adapter) — REAL Docker socket,
REAL pinned Gitleaks image, no mocks.

Confirms, against a REAL daemon, that `GitleaksAdapter.scan()` + `parse()`
correctly detect a deliberately-planted FAKE secret in a small fixture
volume, and correctly report a clean scan when none is present. The planted
secret is a synthetic, randomly-generated hex string — never a real
credential, and deliberately NOT shaped like any real provider's key format
(e.g. Stripe's `sk_test_`/`sk_live_` prefix), because a provider-shaped
fixture — even a genuinely fake one — trips GitHub's own push-protection
secret scanning on this repo, which pattern-matches on key FORMAT alone (see
`_PLANTED_SECRET` below for the empirical proof it still gets detected).

Skips automatically if no Docker socket is reachable (`client.ping()`
fails), matching `test_docker_container_runner_live.py`'s pattern.

This test does NOT exercise `GitCheckout` — it prepares its own fixture
volume directly (via a throwaway root container, same technique as
`GitCheckout._prepare_volume_permissions`) so the Gitleaks adapter is
provable in isolation, per this module's PR2 scope (checkout -> scan wiring
is PR3).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import docker
import pytest

from orchestrator.domain.value_objects.enums import FindingSeverity
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksAdapter

pytestmark = pytest.mark.integration

#: Synthetic, randomly-generated 64-char hex string — NOT a real credential
#: and NOT shaped like any real provider's key format. Matches gitleaks'
#: `generic-api-key` rule deterministically — confirmed empirically against
#: the real pinned image (`docker run ... ghcr.io/gitleaks/gitleaks:v8.30.1`
#: over a fixture assigning this value to `fake_secret`: exit code 2, one
#: finding, `RuleID: generic-api-key`). A provider-shaped fixture (e.g.
#: Stripe's published example `sk_test_...` key, used here previously) —
#: even a genuinely fake one — trips GitHub's own push-protection secret
#: scanning on this repo, which pattern-matches on key FORMAT alone; a
#: generic high-entropy string sidesteps that while still proving the
#: adapter's real point: a secret gets detected by the REAL pinned Gitleaks
#: image. AWS's similarly-famous `AKIA...EXAMPLE` key was considered too, but
#: gitleaks' default config explicitly allowlists any AWS access-token match
#: ending in `EXAMPLE` (`aws-access-token` rule) to suppress doc-sourced
#: false positives — confirmed empirically when that key produced zero
#: findings against the real image.
_PLANTED_SECRET = "9e238adb97cec7687b74530552f3f826bb6fa74f9b82b4f72d526cf0f07f2bc0"


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
    client: docker.DockerClient, volume_name: str, settings: Settings, *, plant_secret: bool
) -> None:
    """Create `volume_name` and write a `checkout/` subdir into it directly
    (bypassing `GitCheckout` — PR2 tests the Gitleaks adapter in isolation).

    Uses a throwaway root container against `settings.scan_git_image`
    (already pulled for PR1's live tests) — hardcoded, no attacker input,
    `network_mode="none"`, mirroring `GitCheckout._prepare_volume_permissions`.
    """
    client.volumes.create(name=volume_name)
    content = f"fake_secret = '{_PLANTED_SECRET}'\n" if plant_secret else "print('clean')\n"
    client.containers.run(
        image=settings.scan_git_image,
        entrypoint="sh",
        command=[
            "-c",
            f'mkdir -p /checkout/checkout && printf "{content}" > /checkout/checkout/config.py',
        ],
        volumes={volume_name: {"bind": "/checkout", "mode": "rw"}},
        network_mode="none",
        remove=True,
    )


def test_gitleaks_adapter_detects_a_real_planted_fake_secret_via_real_docker(
    docker_client: docker.DockerClient,
) -> None:
    settings = _settings()
    volume_name = f"scan-live-gitleaks-{uuid.uuid4().hex}"
    _prepare_fixture_volume(docker_client, volume_name, settings, plant_secret=True)

    try:
        runner = DockerContainerRunner(client=docker_client)
        adapter = GitleaksAdapter(runner=runner, settings=settings)

        result = adapter.scan(volume_name)
        assert result.exit_code == 2, f"expected leaks-found exit 2, got {result.exit_code}"
        assert result.timed_out is False

        scan_task_id = uuid.uuid4()
        findings = adapter.parse(result, scan_task_id)

        assert len(findings) >= 1
        finding = findings[0]
        assert finding.scan_task_id == scan_task_id
        assert finding.severity == FindingSeverity.HIGH
        assert finding.rule_id == "generic-api-key"
        assert finding.file_path is not None
        assert "config.py" in finding.file_path
        assert finding.line_number is not None and finding.line_number >= 1
        assert finding.snippet is not None and _PLANTED_SECRET in finding.snippet
        assert finding.fingerprint
    finally:
        docker_client.volumes.get(volume_name).remove(force=True)

    remaining = docker_client.containers.list(
        all=True, filters={"ancestor": settings.scan_container_image}
    )
    assert remaining == [], "gitleaks container was not force-removed after completion"


def test_gitleaks_adapter_reports_zero_findings_on_a_real_clean_scan(
    docker_client: docker.DockerClient,
) -> None:
    settings = _settings()
    volume_name = f"scan-live-gitleaks-clean-{uuid.uuid4().hex}"
    _prepare_fixture_volume(docker_client, volume_name, settings, plant_secret=False)

    try:
        runner = DockerContainerRunner(client=docker_client)
        adapter = GitleaksAdapter(runner=runner, settings=settings)

        result = adapter.scan(volume_name)
        assert result.exit_code == 0, f"expected clean exit 0, got {result.exit_code}"

        findings = adapter.parse(result, uuid.uuid4())
        assert findings == []
    finally:
        docker_client.volumes.get(volume_name).remove(force=True)
