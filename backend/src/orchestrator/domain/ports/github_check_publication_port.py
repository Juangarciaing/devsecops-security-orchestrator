"""`GitHubCheckPublicationPort` — persistence contract for
`GitHubCheckPublication`. Framework-free: MUST NOT import SQLAlchemy."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from orchestrator.domain.entities.github_check_publication import GitHubCheckPublication


class GitHubCheckPublicationPort(ABC):
    """Async persistence contract, including PR2's `FOR UPDATE SKIP LOCKED`
    claim and owner-CAS complete/release (design: "Dispatch and lease")."""

    @abstractmethod
    async def create(self, publication: GitHubCheckPublication) -> None:
        """Atomically persist `publication` as a new outbox row."""

    @abstractmethod
    async def claim_due(
        self, limit: int, owner: str, lease_until: datetime
    ) -> list[GitHubCheckPublication]:
        """Exclusively claim up to `limit` due rows (`PENDING`, or `CLAIMED`
        with an expired `lease_until`) for `owner` via `FOR UPDATE SKIP
        LOCKED`; `limit`/`lease_until` are explicit caller-supplied bounds.
        """

    @abstractmethod
    async def mark_delivered(
        self, publication_id: uuid.UUID, owner: str, *, external_id: str, check_run_id: int
    ) -> bool:
        """Owner-CAS: mark `publication_id` `DELIVERED`, persist the
        GitHub-side `external_id`/`check_run_id` a successful publish
        returned (design: "GitHub identity" — enables a future PATCH-by-id
        instead of a repeated lookup-by-name), and clear its lease only
        while `owner` still holds it; return `False` otherwise."""

    @abstractmethod
    async def release(self, publication_id: uuid.UUID, owner: str) -> bool:
        """Owner-CAS: release `publication_id` back to `PENDING`, mirroring
        `mark_delivered`'s ownership check."""
