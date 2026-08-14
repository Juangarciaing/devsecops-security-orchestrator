"""`SqlAlchemyGitHubCheckPublicationRepository` — concrete
`GitHubCheckPublicationPort` adapter, mirroring `SqlAlchemyWebhookDeliveryRepository`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.github_check_publication import GitHubCheckPublication
from orchestrator.domain.ports.github_check_publication_port import GitHubCheckPublicationPort
from orchestrator.domain.value_objects.enums import GitHubCheckPublicationStatus
from orchestrator.infrastructure.db.mappers import (
    github_check_publication_to_entity,
    github_check_publication_to_model,
)
from orchestrator.infrastructure.db.models.github_check_publication import (
    GitHubCheckPublicationModel,
)


class SqlAlchemyGitHubCheckPublicationRepository(GitHubCheckPublicationPort):
    """`GitHubCheckPublicationPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, publication: GitHubCheckPublication) -> None:
        model = github_check_publication_to_model(publication)
        self._session.add(model)
        await self._session.flush()

    async def claim_due(
        self, limit: int, owner: str, lease_until: datetime
    ) -> list[GitHubCheckPublication]:
        """`FOR UPDATE SKIP LOCKED` over the due predicate (`PENDING`, or
        `CLAIMED` with an expired lease), then claim the locked rows for
        `owner` in this same transaction so a concurrent identical query
        skips them instead of double-claiming.
        """
        now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, matches `created_at`
        due_predicate = or_(
            GitHubCheckPublicationModel.status == GitHubCheckPublicationStatus.PENDING,
            and_(
                GitHubCheckPublicationModel.status == GitHubCheckPublicationStatus.CLAIMED,
                GitHubCheckPublicationModel.lease_until < now,
            ),
        )
        stmt = (
            select(GitHubCheckPublicationModel)
            .where(due_predicate)
            .order_by(GitHubCheckPublicationModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        claimed_models = list(result.scalars().all())
        for model in claimed_models:
            model.status = GitHubCheckPublicationStatus.CLAIMED
            model.leased_by = owner
            model.lease_until = lease_until
        await self._session.flush()
        return [github_check_publication_to_entity(model) for model in claimed_models]

    async def mark_delivered(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        external_id: str,
        check_run_id: int,
        attempt_count: int,
    ) -> bool:
        return await self._owner_cas_update(
            publication_id,
            owner,
            status=GitHubCheckPublicationStatus.DELIVERED,
            external_id=external_id,
            check_run_id=check_run_id,
            attempt_count=attempt_count,
        )

    async def release(self, publication_id: uuid.UUID, owner: str) -> bool:
        return await self._owner_cas_update(
            publication_id, owner, status=GitHubCheckPublicationStatus.PENDING
        )

    async def reschedule(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        lease_until: datetime,
        attempt_count: int,
    ) -> bool:
        """Owner-CAS (PR6): extend `owner`'s lease and record
        `attempt_count`, staying `CLAIMED` — the next sweep cycle reclaims
        it once `lease_until` elapses (design: no in-process retry sleep)."""
        return await self._owner_cas_update(
            publication_id,
            owner,
            status=GitHubCheckPublicationStatus.CLAIMED,
            lease_until=lease_until,
            leased_by=owner,
            attempt_count=attempt_count,
        )

    async def mark_dead(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        attempt_count: int,
        dead_letter_reason: str,
    ) -> bool:
        """Owner-CAS (PR6): terminally `DEAD`, recording `attempt_count`/
        `dead_letter_reason` and clearing the lease."""
        return await self._owner_cas_update(
            publication_id,
            owner,
            status=GitHubCheckPublicationStatus.DEAD,
            attempt_count=attempt_count,
            dead_letter_reason=dead_letter_reason,
        )

    async def replay(self, publication_id: uuid.UUID) -> bool:
        """Protected replay (PR6): NOT owner-scoped — an explicit,
        deliberate operation, never invoked automatically by the sweep.
        Resets a `DISABLED`/`DEAD` row to `PENDING`, clearing
        `dead_letter_reason` while preserving `attempt_count`; any other
        current status is a no-op (`False`)."""
        stmt = (
            update(GitHubCheckPublicationModel)
            .where(
                GitHubCheckPublicationModel.id == publication_id,
                GitHubCheckPublicationModel.status.in_(
                    (GitHubCheckPublicationStatus.DISABLED, GitHubCheckPublicationStatus.DEAD)
                ),
            )
            .values(
                status=GitHubCheckPublicationStatus.PENDING,
                dead_letter_reason=None,
                leased_by=None,
                lease_until=None,
            )
        )
        result = cast("CursorResult[object]", await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount == 1

    async def _owner_cas_update(
        self,
        publication_id: uuid.UUID,
        owner: str,
        *,
        status: GitHubCheckPublicationStatus,
        lease_until: datetime | None = None,
        leased_by: str | None = None,
        attempt_count: int | None = None,
        dead_letter_reason: str | None = None,
        external_id: str | None = None,
        check_run_id: int | None = None,
    ) -> bool:
        """Owner-CAS transition: only a row still leased to `owner` moves to
        `status`. `lease_until`/`leased_by` default to clearing the lease
        (the `mark_delivered`/`release` precedent); `reschedule` overrides
        both to keep it claimed. `attempt_count`/`dead_letter_reason`
        (PR6) and `external_id`/`check_run_id` (PR5 fix: only
        `mark_delivered` ever passes them), when given, are set
        unconditionally alongside `status`."""
        values: dict[str, object] = {
            "status": status,
            "leased_by": leased_by,
            "lease_until": lease_until,
        }
        if attempt_count is not None:
            values["attempt_count"] = attempt_count
        if dead_letter_reason is not None:
            values["dead_letter_reason"] = dead_letter_reason
        if external_id is not None:
            values["external_id"] = external_id
        if check_run_id is not None:
            values["check_run_id"] = check_run_id
        stmt = (
            update(GitHubCheckPublicationModel)
            .where(
                GitHubCheckPublicationModel.id == publication_id,
                GitHubCheckPublicationModel.leased_by == owner,
            )
            .values(**values)
        )
        result = cast("CursorResult[object]", await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount == 1
