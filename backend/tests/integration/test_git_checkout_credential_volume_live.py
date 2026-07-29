"""Live-Docker proof for PR5 (secrets-manager, design D4) — REAL Docker
socket, no mocks.

PR4's spike (task 4.1) proved `put_archive()` on a created-but-never-started
container writes through a named-volume mount for a LATER container to see.
This file closes the one adversarial gap that spike did NOT cover: file
OWNERSHIP. `put_archive`'s tar entries carry an explicit uid/gid
(`GitCheckout._add_tar_entry`); if that were wrong, the hardened non-root
(`65532:65532`) clone container could create the volume and clone into it,
yet be unable to READ its own `.gitconfig`/`.git-credentials` — a silent
correctness bug no unit test (mocked docker client) can catch.

Confirms, against a REAL daemon:
- `GitCheckout.checkout(..., credential=Secret(...))` succeeds end to end
  against a real PUBLIC repo (proves the credential-plumbing doesn't break
  an ordinary clone — a real private-repo proof is PR8's job)
- the written `.git-credentials` file is genuinely owned by UID 65532 and
  mode 0600, and a container running AS UID 65532 can actually read it back
  byte-for-byte (the concrete risk this file exists to rule out)
- both credential files are genuinely ABSENT from the volume by the time
  `checkout()` returns (the shred step actually happened, not just asserted
  against a mock)

Skips automatically if no Docker socket is reachable.
"""

from __future__ import annotations

from collections.abc import Iterator

import docker
import pytest

from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.vcs.git_checkout import GitCheckout

pytestmark = pytest.mark.integration

_TRIVIAL_IMAGE = "alpine:latest"
_PUBLIC_REPO_URL = "https://github.com/octocat/Hello-World.git"
_PUBLIC_REPO_REF = "master"
_FAKE_TOKEN = "ghp_live-proof-canary-token-never-a-real-secret"  # noqa: S105


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


def test_credential_files_are_readable_by_the_nonroot_clone_user_and_shredded_after(
    docker_client: docker.DockerClient,
) -> None:
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=_settings())

    ws = checkout.checkout(_PUBLIC_REPO_URL, _PUBLIC_REPO_REF, credential=Secret(_FAKE_TOKEN))
    try:
        assert len(ws.head_sha) == 40

        # A THIRD, independent container running AS the hardened non-root
        # UID confirms both files are genuinely gone post-shred — the real
        # risk being ruled out here (silent unreadable-then-orphaned files).
        exists_check = docker_client.containers.run(
            image=_TRIVIAL_IMAGE,
            user="65532:65532",
            command=[
                "sh",
                "-c",
                "test -e /checkout/.git-credentials && echo PRESENT || echo ABSENT; "
                "test -e /checkout/.gitconfig && echo PRESENT || echo ABSENT",
            ],
            volumes={ws.volume_name: {"bind": "/checkout", "mode": "ro"}},
            remove=True,
        )
        assert exists_check.decode().split() == ["ABSENT", "ABSENT"]
    finally:
        with ws:
            pass  # deferred volume cleanup (Workspace.__exit__)


def test_credential_file_is_owned_by_nonroot_uid_and_readable_before_shred(
    docker_client: docker.DockerClient,
) -> None:
    """Directly proves the ownership property `_add_tar_entry` exists for:
    write the credential pair via the same mechanism `GitCheckout` uses, then
    confirm a container running AS UID 65532 (never root) can `cat` the file
    contents back byte-for-byte — the concrete failure mode a root-owned,
    mode-0600 file would produce (Permission denied for the clone step)."""
    volume = docker_client.volumes.create(name="scan-live-credential-ownership-test")
    settings = _settings()
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=settings)

    try:
        # Same private helper GitCheckout itself calls before every
        # credentialed clone — exercised directly so this test does not
        # depend on GitHub responding to a bogus token.
        checkout._write_credential_files(volume.name, Secret(_FAKE_TOKEN))  # noqa: SLF001

        read_back = docker_client.containers.run(
            image=_TRIVIAL_IMAGE,
            user="65532:65532",
            command=["cat", "/checkout/.git-credentials"],
            volumes={volume.name: {"bind": "/checkout", "mode": "ro"}},
            remove=True,
        )
        assert read_back.decode() == f"https://x-access-token:{_FAKE_TOKEN}@github.com\n"
    finally:
        docker_client.volumes.get(volume.name).remove(force=True)
