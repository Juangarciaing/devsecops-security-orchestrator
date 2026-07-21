"""`SqlAlchemyScanRunRepository` — first concrete `ScanRunPort` adapter,
following the pattern established by `SqlAlchemyCodeRepositoryRepository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.infrastructure.db.mappers import scan_run_to_entity, scan_run_to_model
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel


class ScanRunNotFoundError(LookupError):
    """Raised when a mutation targets a `ScanRun` id that does not exist."""


class SqlAlchemyScanRunRepository(ScanRunPort):
    """`ScanRunPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        model = await self._session.get(ScanRunModel, scan_run_id)
        return scan_run_to_entity(model) if model is not None else None

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        stmt = select(ScanRunModel).where(ScanRunModel.repository_id == repository_id)
        result = await self._session.execute(stmt)
        return [scan_run_to_entity(model) for model in result.scalars().all()]

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        stmt = (
            select(ScanRunModel)
            .order_by(ScanRunModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [scan_run_to_entity(model) for model in result.scalars().all()]

    async def create(self, scan_run: ScanRun) -> ScanRun:
        model = scan_run_to_model(scan_run)
        self._session.add(model)
        await self._session.flush()
        return scan_run_to_entity(model)

    async def update_status(
        self,
        scan_run_id: uuid.UUID,
        status: ScanRunStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> ScanRun:
        """Update `status` and, when explicitly given, `started_at`/`completed_at`.

        `started_at`/`completed_at` default to `None`, meaning "leave
        unchanged" — never resets an already-set timestamp back to `None`.
        Adapter-only extension beyond `ScanRunPort` (worker state machine, D2/D5).
        """
        model = await self._session.get(ScanRunModel, scan_run_id)
        if model is None:
            raise ScanRunNotFoundError(scan_run_id)
        model.status = status
        if started_at is not None:
            model.started_at = started_at
        if completed_at is not None:
            model.completed_at = completed_at
        await self._session.flush()
        return scan_run_to_entity(model)

    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        """Powers `GET /repositories/{id}/diff` (Module 12b). `id` is a random
        `uuid4` (never monotonic) — `created_at` is the real ordering key,
        `id` is only a deterministic tiebreak, mirroring the `(created_at,
        id)` convention already used elsewhere in this adapter/`FindingRepository`.
        """
        stmt = (
            select(ScanRunModel)
            .where(
                ScanRunModel.repository_id == repository_id,
                ScanRunModel.status == ScanRunStatus.COMPLETED,
            )
            .order_by(ScanRunModel.created_at.desc(), ScanRunModel.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [scan_run_to_entity(model) for model in result.scalars().all()]

    async def update_commit_sha(self, scan_run_id: uuid.UUID, commit_sha: str) -> ScanRun:
        """Persist the resolved real HEAD SHA onto `ScanRun.commit_sha`.

        `commit_sha` at creation may be a placeholder branch/ref name
        (Module 5); Module 6's `GitCheckout` resolves the actual HEAD SHA via
        `git rev-parse` and this persists it back. Adapter-only extension
        beyond `ScanRunPort` (worker flow), matching `update_status`'s
        precedent for adapter-only kwargs beyond the abstract signature.
        """
        model = await self._session.get(ScanRunModel, scan_run_id)
        if model is None:
            raise ScanRunNotFoundError(scan_run_id)
        model.commit_sha = commit_sha
        await self._session.flush()
        return scan_run_to_entity(model)
