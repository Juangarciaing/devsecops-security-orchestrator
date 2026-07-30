"""Live-optional proof for secrets-manager PR8 (task 8.2) — a REAL private
GitHub repository scanned end to end with a REAL stored personal-access
token, no mocks.

PR5/PR6 already proved every piece of this path against fakes/mocks and a
live Docker daemon using a synthetic canary token against a *public* repo
(`test_git_checkout_credential_volume_live.py`, `test_process_scan_credentials.py`).
This file is the one remaining gap: an actual private repository that
genuinely requires the credential to clone at all. It exists to be run by a
maintainer who has both a disposable private GitHub repo and a PAT scoped
to read it — neither of which is available in this sandbox.

Skips automatically (not failure, not silent absence) when:
- no Docker socket is reachable (mirrors every other `*_live.py` file's
  `docker_client` fixture), OR
- `SECRETS_MANAGER_LIVE_PRIVATE_REPO_URL` and
  `SECRETS_MANAGER_LIVE_PRIVATE_REPO_PAT` are not both set in the
  environment.

To actually exercise this test: create a throwaway private GitHub repo,
generate a PAT scoped to read it, and run

    SECRETS_MANAGER_LIVE_PRIVATE_REPO_URL=https://github.com/<owner>/<private-repo>.git \\
    SECRETS_MANAGER_LIVE_PRIVATE_REPO_PAT=ghp_... \\
    SECRETS_MANAGER_LIVE_PRIVATE_REPO_REF=main \\
    uv run pytest tests/integration/test_private_repo_scan_live.py -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import docker
import pytest

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.container.scan_execution_factory import create_scan_execution

pytestmark = pytest.mark.integration

_REPO_URL_ENV_VAR = "SECRETS_MANAGER_LIVE_PRIVATE_REPO_URL"
_PAT_ENV_VAR = "SECRETS_MANAGER_LIVE_PRIVATE_REPO_PAT"
_REF_ENV_VAR = "SECRETS_MANAGER_LIVE_PRIVATE_REPO_REF"
_DEFAULT_REF = "main"


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


def _require_live_private_repo_config() -> tuple[str, str, str]:
    """Skip (not fail) when no real private repo + PAT is configured for
    this sandbox/CI environment — this proof is optional by design (design
    "Testing Strategy": Live (optional))."""
    repo_url = os.environ.get(_REPO_URL_ENV_VAR)
    pat = os.environ.get(_PAT_ENV_VAR)
    if not repo_url or not pat:
        pytest.skip(
            "no real private GitHub repo + PAT configured for this optional live "
            f"proof — set {_REPO_URL_ENV_VAR} and {_PAT_ENV_VAR} "
            f"(optionally also {_REF_ENV_VAR}, defaults to "
            f"'{_DEFAULT_REF}') to exercise it (secrets-manager PR8, task 8.2)"
        )
    ref = os.environ.get(_REF_ENV_VAR, _DEFAULT_REF)
    return repo_url, pat, ref


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_private_repo_scans_end_to_end_with_a_real_stored_credential(
    docker_client: docker.DockerClient,
) -> None:
    repo_url, pat, ref = _require_live_private_repo_config()
    settings = _settings()
    runner = DockerContainerRunner(client=docker_client)
    execution = create_scan_execution(runner, docker_client, settings, ScannerType.SECRETS)

    result = execution.execute(
        repo_url, ref, uuid.uuid4(), ScannerType.SECRETS, credential=Secret(pat)
    )

    assert len(result.head_sha) == 40
    assert isinstance(result.findings, list)
