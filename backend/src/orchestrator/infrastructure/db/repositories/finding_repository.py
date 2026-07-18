"""`SqlAlchemyFindingRepository` — concrete `FindingPort` adapter, following
the pattern established by `SqlAlchemyCodeRepositoryRepository`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.value_objects.enums import FindingStatus
from orchestrator.infrastructure.db.mappers import finding_to_entity, finding_to_model
from orchestrator.infrastructure.db.models.finding import FindingModel


class FindingNotFoundError(LookupError):
    """Raised when a mutation targets a `Finding` id that does not exist."""


class SqlAlchemyFindingRepository(FindingPort):
    """`FindingPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        model = await self._session.get(FindingModel, finding_id)
        return finding_to_entity(model) if model is not None else None

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        stmt = select(FindingModel).where(FindingModel.scan_task_id == scan_task_id)
        result = await self._session.execute(stmt)
        return [finding_to_entity(model) for model in result.scalars().all()]

    async def create(self, finding: Finding) -> Finding:
        model = finding_to_model(finding)
        self._session.add(model)
        await self._session.flush()
        return finding_to_entity(model)

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        model = await self._session.get(FindingModel, finding_id)
        if model is None:
            raise FindingNotFoundError(finding_id)
        model.status = status
        await self._session.flush()
        return finding_to_entity(model)

    async def count_by_scan_task(self, scan_task_id: uuid.UUID) -> int:
        """Return the number of `Finding`s for `scan_task_id` without loading rows.

        Adapter-only helper (not part of `FindingPort`) — powers the
        `GET /scans/{id}` findings COUNT (design's non-goal: no findings
        listing endpoint in this module).
        """
        stmt = (
            select(func.count())
            .select_from(FindingModel)
            .where(FindingModel.scan_task_id == scan_task_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
