"""`SqlAlchemyScanTargetRepository` — concrete `ScanTargetPort` adapter,
mirroring `SqlAlchemyCodeRepositoryRepository`'s pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort
from orchestrator.infrastructure.db.mappers import scan_target_to_entity, scan_target_to_model
from orchestrator.infrastructure.db.models.scan_target import ScanTargetModel


class ScanTargetNotFoundError(LookupError):
    """Raised when a mutation targets a `ScanTarget` id that does not exist."""


class SqlAlchemyScanTargetRepository(ScanTargetPort):
    """`ScanTargetPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, target_id: uuid.UUID) -> ScanTarget | None:
        model = await self._session.get(ScanTargetModel, target_id)
        return scan_target_to_entity(model) if model is not None else None

    async def get_by_url(self, target_url: str) -> ScanTarget | None:
        stmt = select(ScanTargetModel).where(ScanTargetModel.target_url == target_url)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return scan_target_to_entity(model) if model is not None else None

    async def list_all(self) -> list[ScanTarget]:
        stmt = select(ScanTargetModel)
        result = await self._session.execute(stmt)
        return [scan_target_to_entity(model) for model in result.scalars().all()]

    async def list_active(self) -> list[ScanTarget]:
        stmt = select(ScanTargetModel).where(ScanTargetModel.is_active.is_(True))
        result = await self._session.execute(stmt)
        return [scan_target_to_entity(model) for model in result.scalars().all()]

    async def create(self, target: ScanTarget) -> ScanTarget:
        model = scan_target_to_model(target)
        self._session.add(model)
        await self._session.flush()
        return scan_target_to_entity(model)

    async def update(self, target: ScanTarget) -> ScanTarget:
        model = await self._session.get(ScanTargetModel, target.id)
        if model is None:
            raise ScanTargetNotFoundError(target.id)
        model.name = target.name
        model.target_url = target.target_url
        # Naive UTC: matches `created_at`'s `func.now()` server_default convention.
        model.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()
        return scan_target_to_entity(model)

    async def soft_delete(self, target_id: uuid.UUID) -> None:
        model = await self._session.get(ScanTargetModel, target_id)
        if model is None:
            return
        model.is_active = False
        await self._session.flush()
