"""`GitHubChecksHttpClient` — mapping resolution + Check Run publish (PR5c).
`FakeGitHubAdapter` fakes both composed dependencies — PR5b's real
`GitHubAppTokenProvider` has its own crypto/cache tests. ALL HTTP is mocked;
NEVER a real GitHub App/installation id or network call (SECURITY).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from orchestrator.domain.entities.github_repository_installation import (
    GitHubRepositoryInstallation,
)
from orchestrator.domain.ports.github_repository_installation_port import (
    GitHubRepositoryInstallationPort,
)
from orchestrator.domain.value_objects.enums import GitHubCheckOutcome
from orchestrator.infrastructure.github.checks_client import GitHubChecksHttpClient


class FakeGitHubAdapter(GitHubRepositoryInstallationPort):
    """Fakes BOTH composed dependencies — the real adapters each have their
    own dedicated test suite; no real JWT/crypto/DB is involved here."""

    def __init__(self) -> None:
        self.saved: dict[uuid.UUID, int] = {}
        self.refresh_calls: list[bool] = []

    async def get_by_repository_id(
        self, repository_id: uuid.UUID
    ) -> GitHubRepositoryInstallation | None:
        installation_id = self.saved.get(repository_id)
        if installation_id is None:
            return None
        return GitHubRepositoryInstallation(
            repository_id=repository_id, installation_id=installation_id
        )

    async def upsert(self, mapping: GitHubRepositoryInstallation) -> None:
        self.saved[mapping.repository_id] = mapping.installation_id

    def mint_app_jwt(self) -> str:
        return "fake-app-jwt"

    async def get_installation_token(
        self, installation_id: int, *, force_refresh: bool = False
    ) -> str:
        self.refresh_calls.append(force_refresh)
        return "ghs_fake-installation-token"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    installation_id: int | None = None,
    adapter: FakeGitHubAdapter | None = None,
    repository_id: uuid.UUID | None = None,
) -> tuple[GitHubChecksHttpClient, uuid.UUID, FakeGitHubAdapter]:
    fake = adapter or FakeGitHubAdapter()
    repo_id = repository_id or uuid.uuid4()
    if installation_id is not None:
        fake.saved[repo_id] = installation_id
    http_client = httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    client = GitHubChecksHttpClient(
        token_provider=fake, installation_port=fake, http_client=http_client
    )
    return client, repo_id, fake


def _unreachable_handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


def test_installation_mapping_is_discovered_once_then_reused_without_a_network_call() -> None:
    repository_id = uuid.uuid4()
    adapter = FakeGitHubAdapter()

    def discover(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 777})

    client, _, _ = _client(discover, adapter=adapter, repository_id=repository_id)
    discovered = asyncio.run(client._resolve_installation_id(repository_id, "acme", "widgets"))
    assert discovered == 777 == adapter.saved[repository_id]

    cached, _, _ = _client(_unreachable_handler, adapter=adapter, repository_id=repository_id)
    reused = asyncio.run(cached._resolve_installation_id(repository_id, "acme", "widgets"))
    assert reused == 777  # no network call — served entirely from the persisted mapping


def _publish_router(
    *,
    check_runs_listing: list[dict[str, object]] | None = None,
    check_run_response_id: int = 999,
    unauthorized_once_on: str | None = None,
    stale_mapping_status: int | None = None,
) -> tuple[Callable[[httpx.Request], httpx.Response], list[str]]:
    """Mocked GitHub-API router for `publish()`'s single-retry paths."""
    calls: list[str] = []
    failure_used = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal failure_used
        path, method = request.url.path, request.method
        calls.append(f"{method} {path}")
        if path.endswith("/installation") and method == "GET":
            return httpx.Response(200, json={"id": 42})
        if path.endswith("/check-runs") and method == "GET":
            return httpx.Response(200, json={"check_runs": check_runs_listing or []})
        if method in ("POST", "PATCH") and not failure_used:
            if method == unauthorized_once_on:
                failure_used = True
                return httpx.Response(401, json={"message": "Bad credentials"})
            if stale_mapping_status is not None:
                failure_used = True
                return httpx.Response(stale_mapping_status, json={"message": "Not Found"})
        if method == "PATCH":  # a real PATCH response echoes the URL's OWN id
            return httpx.Response(200, json={"id": int(path.rsplit("/", 1)[-1])})
        return httpx.Response(201, json={"id": check_run_response_id})

    return handler, calls


def _publish_kwargs(**overrides: object) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "repository_id": uuid.uuid4(),
        "owner": "acme",
        "repo": "widgets",
        "head_sha": "a" * 40,
        "check_name": "security/orchestrator",
        "external_id": "github-checks:fake-scan-run",
        "check_run_id": None,
        "outcome": GitHubCheckOutcome.SUCCESS,
        "summary": "0 findings",
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.parametrize(
    ("check_runs_listing", "expected_id", "post_expected"),
    [
        pytest.param(None, 999, True, id="no-match-creates"),
        pytest.param(
            [{"id": 321, "external_id": "github-checks:fake-scan-run"}],
            321,
            False,
            id="match-reuses",
        ),
    ],
)
def test_publish_creates_or_reuses_a_check_run_based_on_the_external_id_lookup(
    check_runs_listing: list[dict[str, object]] | None, expected_id: int, post_expected: bool
) -> None:
    handler, calls = _publish_router(
        check_runs_listing=check_runs_listing, check_run_response_id=999
    )
    client, repository_id, _ = _client(handler, installation_id=42)
    result = asyncio.run(client.publish(**_publish_kwargs(repository_id=repository_id)))
    assert result.check_run_id == expected_id
    assert ("POST /repos/acme/widgets/check-runs" in calls) is post_expected


def test_publish_patches_the_persisted_check_run_id_without_a_lookup() -> None:
    """A persisted `check_run_id` skips the lookup and goes straight to `PATCH`."""
    handler, calls = _publish_router(check_run_response_id=555)
    client, repository_id, _ = _client(handler, installation_id=42)
    result = asyncio.run(
        client.publish(**_publish_kwargs(repository_id=repository_id, check_run_id=555))
    )
    assert result.check_run_id == 555
    assert "PATCH /repos/acme/widgets/check-runs/555" in calls
    assert not any("check-runs" in call and not call.startswith("PATCH") for call in calls)


def test_publish_refreshes_the_token_once_after_a_401_and_retries_successfully() -> None:
    handler, _ = _publish_router(check_run_response_id=888, unauthorized_once_on="POST")
    client, repository_id, fake = _client(handler, installation_id=42)
    result = asyncio.run(client.publish(**_publish_kwargs(repository_id=repository_id)))
    assert result.check_run_id == 888
    assert fake.refresh_calls == [False, True, False]  # refreshed exactly once, never a loop


def test_publish_refreshes_the_installation_mapping_once_after_a_404_and_retries() -> None:
    """A stale `installation_id` 404s; the mapping is refreshed ONCE."""
    handler, calls = _publish_router(check_run_response_id=444, stale_mapping_status=404)
    client, repository_id, fake = _client(handler, installation_id=999)  # stale
    result = asyncio.run(client.publish(**_publish_kwargs(repository_id=repository_id)))
    assert result.check_run_id == 444
    assert calls.count("GET /repos/acme/widgets/installation") == 1
    assert fake.saved[repository_id] == 42  # refreshed to the discovered id
