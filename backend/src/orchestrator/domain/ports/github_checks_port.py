"""`GitHubChecksPort` — delivery contract for publishing one GitHub Check Run.
Framework-free: MUST NOT import `httpx`/`jwt`/crypto — those belong to the
`checks_client` adapter."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from orchestrator.domain.value_objects.enums import GitHubCheckOutcome


@dataclass(slots=True, frozen=True)
class PublishedCheck:
    """The GitHub-side Check Run identity, persisted back onto the outbox row."""

    check_run_id: int
    external_id: str


class GitHubChecksPort(ABC):
    """Create-or-update keyed by `external_id`/`check_run_id` — retries MUST
    update the existing run, never create a second one."""

    @abstractmethod
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
        """`PATCH` `check_run_id` if known, else reuse an `external_id` lookup
        match, else create one."""
