"""`GitHubChecksHttpClient` — mapping resolution + Check Run publish (PR5c).
Composes an `InstallationTokenSource` (PR5b's `GitHubAppTokenProvider` fits
structurally). One 401 OR one 403/404 retry, never both/looped (PR6's job);
dup reconciliation is also PR6's.
"""

from __future__ import annotations

import uuid
from typing import Protocol

import httpx

from orchestrator.domain.entities.github_repository_installation import (
    GitHubRepositoryInstallation,
)
from orchestrator.domain.ports.github_checks_port import GitHubChecksPort, PublishedCheck
from orchestrator.domain.ports.github_repository_installation_port import (
    GitHubRepositoryInstallationPort,
)
from orchestrator.domain.value_objects.enums import GitHubCheckOutcome


class InstallationTokenSource(Protocol):
    """Structural contract for the composed token-acquisition dependency.
    (Left as a `Protocol` rather than importing `GitHubAppTokenProvider`
    directly — this file stays agnostic to how token acquisition/caching is
    implemented, matching this codebase's existing composition pattern.)"""

    def mint_app_jwt(self) -> str: ...

    async def get_installation_token(
        self, installation_id: int, *, force_refresh: bool = False
    ) -> str: ...


def _headers(authorization: str) -> dict[str, str]:
    return {"Authorization": authorization, "Accept": "application/vnd.github+json"}


#: GitHub's own per-page cap for this endpoint.
_CHECK_RUNS_PAGE_SIZE = 100


class GitHubChecksHttpClient(GitHubChecksPort):
    """Owns mapping resolution and Check Run lookup/publish only."""

    def __init__(
        self,
        *,
        token_provider: InstallationTokenSource,
        installation_port: GitHubRepositoryInstallationPort,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._tokens = token_provider
        self._installation_port = installation_port
        self._http = http_client

    async def _resolve_installation_id(
        self, repository_id: uuid.UUID, owner: str, repo: str, *, force_refresh: bool = False
    ) -> int:
        """`force_refresh` bypasses the persisted mapping for the 403/404 retry."""
        if not force_refresh:
            mapping = await self._installation_port.get_by_repository_id(repository_id)
            if mapping is not None:
                return mapping.installation_id
        app_jwt = self._tokens.mint_app_jwt()
        response = await self._http.get(
            f"/repos/{owner}/{repo}/installation", headers=_headers(f"Bearer {app_jwt}")
        )
        response.raise_for_status()
        installation_id = int(response.json()["id"])
        await self._installation_port.upsert(
            GitHubRepositoryInstallation(
                repository_id=repository_id, installation_id=installation_id
            )
        )
        return installation_id

    async def _find_existing_check_run_id(
        self, token: str, owner: str, repo: str, head_sha: str, check_name: str, external_id: str
    ) -> int | None:
        """Paginates through EVERY page of check runs for `head_sha`
        (GitHub caps each page at `_CHECK_RUNS_PAGE_SIZE`) — a commit that
        has accumulated more than one page of check runs would otherwise
        make an unpaginated first-page-only lookup silently miss an
        existing `external_id` match, causing `_publish_once` to `POST` a
        duplicate Check Run instead of `PATCH`ing the real one (design:
        "retries MUST update the existing run, never create a second
        one"). First match wins (dup reconciliation across the returned
        set is PR6's)."""
        page = 1
        while True:
            lookup = await self._http.get(
                f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
                params={
                    "check_name": check_name,
                    "per_page": _CHECK_RUNS_PAGE_SIZE,
                    "page": page,
                },
                headers=_headers(f"token {token}"),
            )
            lookup.raise_for_status()
            check_runs = lookup.json().get("check_runs", [])
            for run in check_runs:
                if run.get("external_id") == external_id:
                    return int(run["id"])
            if len(check_runs) < _CHECK_RUNS_PAGE_SIZE:
                return None
            page += 1

    async def _publish_once(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        head_sha: str,
        check_name: str,
        external_id: str,
        check_run_id: int | None,
        outcome: GitHubCheckOutcome,
        summary: str,
    ) -> PublishedCheck:
        """Lookup-before-create when no `check_run_id` is given yet; first
        match wins (dup reconciliation is PR6's)."""
        token = await self._tokens.get_installation_token(installation_id)
        resolved_id = check_run_id
        if resolved_id is None:
            resolved_id = await self._find_existing_check_run_id(
                token, owner, repo, head_sha, check_name, external_id
            )
        payload = {
            "name": check_name,
            "head_sha": head_sha,
            "external_id": external_id,
            "status": "completed",
            "conclusion": outcome.value,
            "output": {"title": check_name, "summary": summary},
        }
        base = f"/repos/{owner}/{repo}/check-runs"
        url = f"{base}/{resolved_id}" if resolved_id is not None else base
        send = self._http.patch if resolved_id is not None else self._http.post
        response = await send(url, json=payload, headers=_headers(f"token {token}"))
        response.raise_for_status()
        return PublishedCheck(check_run_id=int(response.json()["id"]), external_id=external_id)

    async def publish(
        self,
        *,
        repository_id: uuid.UUID,
        owner: str,
        repo: str,
        head_sha: str,
        check_name: str,
        external_id: str,
        check_run_id: int | None,
        outcome: GitHubCheckOutcome,
        summary: str,
    ) -> PublishedCheck:
        """One 401 OR one 403/404 retry — never both, never a loop (PR6's job)."""
        installation_id = await self._resolve_installation_id(repository_id, owner, repo)
        args = (owner, repo, head_sha, check_name, external_id, check_run_id, outcome, summary)
        try:
            return await self._publish_once(installation_id, *args)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                await self._tokens.get_installation_token(installation_id, force_refresh=True)
            elif status in (403, 404):
                installation_id = await self._resolve_installation_id(
                    repository_id, owner, repo, force_refresh=True
                )
            else:
                raise
            return await self._publish_once(installation_id, *args)
