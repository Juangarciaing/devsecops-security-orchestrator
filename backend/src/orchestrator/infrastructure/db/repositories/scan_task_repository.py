"""`SqlAlchemyScanTaskRepository` — concrete `ScanTaskPort` adapter, following
the pattern established by `SqlAlchemyCodeRepositoryRepository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus
from orchestrator.infrastructure.db.mappers import scan_task_to_entity, scan_task_to_model
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel


class ScanTaskNotFoundError(LookupError):
    """Raised when a mutation targets a `ScanTask` id that does not exist."""


class SqlAlchemyScanTaskRepository(ScanTaskPort):
    """`ScanTaskPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, scan_task_id: uuid.UUID) -> ScanTask | None:
        model = await self._session.get(ScanTaskModel, scan_task_id)
        return scan_task_to_entity(model) if model is not None else None

    async def list_by_scan_run(self, scan_run_id: uuid.UUID) -> list[ScanTask]:
        stmt = select(ScanTaskModel).where(ScanTaskModel.scan_run_id == scan_run_id)
        result = await self._session.execute(stmt)
        return [scan_task_to_entity(model) for model in result.scalars().all()]

    async def create(self, scan_task: ScanTask) -> ScanTask:
        model = scan_task_to_model(scan_task)
        self._session.add(model)
        await self._session.flush()
        return scan_task_to_entity(model)

    async def update_status(
        self,
        scan_task_id: uuid.UUID,
        status: ScanTaskStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error_message: str | None = None,
    ) -> ScanTask:
        """Update `status` and, when explicitly given, timestamps/`error_message`.

        `started_at`/`completed_at`/`error_message` default to `None`,
        meaning "leave unchanged" — never resets an already-set value back to
        `None`. Adapter-only extension beyond `ScanTaskPort` (worker state
        machine, D2/D5).
        """
        model = await self._session.get(ScanTaskModel, scan_task_id)
        if model is None:
            raise ScanTaskNotFoundError(scan_task_id)
        model.status = status
        if started_at is not None:
            model.started_at = started_at
        if completed_at is not None:
            model.completed_at = completed_at
        if error_message is not None:
            model.error_message = error_message
        await self._session.flush()
        return scan_task_to_entity(model)

    async def find_active_task(
        self, repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        """Join `ScanTaskModel` -> `ScanRunModel` (D3): only `PENDING`/`RUNNING`
        tasks for the given repository/commit/scanner_type suppress re-trigger.
        """
        stmt = (
            select(ScanTaskModel)
            .join(ScanRunModel, ScanTaskModel.scan_run_id == ScanRunModel.id)
            .where(
                ScanRunModel.repository_id == repository_id,
                ScanRunModel.commit_sha == commit_sha,
                ScanTaskModel.scanner_type == scanner_type,
                ScanTaskModel.status.in_((ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING)),
            )
        )
        result = await self._session.execute(stmt)
        model = result.scalars().first()
        return scan_task_to_entity(model) if model is not None else None
