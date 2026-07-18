"""`SqlAlchemyScanRunRepository` — first concrete `ScanRunPort` adapter,
following the pattern established by `SqlAlchemyCodeRepositoryRepository`.
"""

from __future__ import annotations

import uuid

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

    async def create(self, scan_run: ScanRun) -> ScanRun:
        model = scan_run_to_model(scan_run)
        self._session.add(model)
        await self._session.flush()
        return scan_run_to_entity(model)

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        model = await self._session.get(ScanRunModel, scan_run_id)
        if model is None:
            raise ScanRunNotFoundError(scan_run_id)
        model.status = status
        await self._session.flush()
        return scan_run_to_entity(model)
