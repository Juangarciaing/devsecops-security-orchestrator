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
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        external_id: str,
        check_run_id: int,
        attempt_count: int,
    ) -> bool:
        """Owner-CAS: mark `publication_id` `DELIVERED`, persist the
        GitHub-side `external_id`/`check_run_id` a successful publish
        returned (design: "GitHub identity" — enables a future PATCH-by-id
        instead of a repeated lookup-by-name) and the TOTAL attempts it
        actually took (including this one — a publication that failed
        twice then succeeded on the third attempt must record 3, not
        whatever an earlier `reschedule` last set), and clear its lease
        only while `owner` still holds it; return `False` otherwise."""

    @abstractmethod
    async def release(self, publication_id: uuid.UUID, owner: str) -> bool:
        """Owner-CAS: release `publication_id` back to `PENDING`, mirroring
        `mark_delivered`'s ownership check."""

    @abstractmethod
    async def reschedule(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        lease_until: datetime,
        attempt_count: int,
    ) -> bool:
        """Owner-CAS (PR6, design: "Dead-letter + replay"): extend a still-
        `CLAIMED` row's lease to `lease_until` and record `attempt_count`,
        so the NEXT sweep cycle (not an in-process sleep) picks it back up
        once the lease expires. Mirrors `mark_delivered`/`release`'s
        ownership check."""

    @abstractmethod
    async def mark_dead(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        attempt_count: int,
        dead_letter_reason: str,
    ) -> bool:
        """Owner-CAS (PR6): terminally mark `publication_id` `DEAD`,
        recording `attempt_count`/`dead_letter_reason` and clearing its
        lease. Mirrors `mark_delivered`'s ownership check."""

    @abstractmethod
    async def replay(self, publication_id: uuid.UUID) -> bool:
        """Protected replay (PR6): reset a `DISABLED` or `DEAD` row back to
        `PENDING`, clearing `dead_letter_reason` while PRESERVING
        `attempt_count` for observability. An explicit, deliberate
        operation — NOT owner-scoped (no sweep ever calls this) and never
        triggered automatically. Returns `False` for any other status."""
