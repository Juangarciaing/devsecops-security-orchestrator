"""`SqlAlchemyFindingRepository` — concrete `FindingPort` adapter, following
the pattern established by `SqlAlchemyCodeRepositoryRepository`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus, ScannerType
from orchestrator.infrastructure.db.mappers import finding_to_entity, finding_to_model
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel


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
        # `created_at`/`updated_at` carry `server_default=func.now()`: after
        # `flush()` those attributes are expired (their real value is only
        # known server-side). `refresh` reloads them inside this awaited
        # async context, before `finding_to_entity` reads them — without it,
        # that synchronous attribute read would trigger a lazy-load outside
        # the greenlet context and raise `MissingGreenlet`. No live caller
        # hits this today (`Finding` always supplies explicit timestamps),
        # but the fix is applied defensively since the bug is latent
        # (identical root cause as `update_status` below).
        await self._session.refresh(model)
        return finding_to_entity(model)

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        model = await self._session.get(FindingModel, finding_id)
        if model is None:
            raise FindingNotFoundError(finding_id)
        model.status = status
        await self._session.flush()
        # `updated_at` has `onupdate=func.now()`: this UPDATE expires it
        # server-side post-flush. Refresh inside the async context before
        # `finding_to_entity` reads it, or the subsequent synchronous
        # attribute access lazy-loads outside the greenlet and raises
        # `MissingGreenlet` (see design's Root Cause section).
        await self._session.refresh(model)
        return finding_to_entity(model)

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        """`FindingPort.bulk_upsert_findings` — DB-atomic `ON CONFLICT` upsert.

        Postgres-specific (`sqlalchemy.dialects.postgresql.insert`), matching
        design D4: read-then-write would race under concurrent same-repo
        scans (TOCTOU), so this relies on Postgres's atomic conflict
        resolution instead. No-op on an empty `findings` list (Postgres
        rejects a zero-row `VALUES` clause).
        """
        if not findings:
            return

        values = [
            {
                "id": finding.id,
                "scan_task_id": finding.scan_task_id,
                "repository_id": repository_id,
                "first_seen_scan_run_id": scan_run_id,
                "last_seen_scan_run_id": scan_run_id,
                "severity": finding.severity,
                "status": finding.status,
                "rule_id": finding.rule_id,
                "title": finding.title,
                "fingerprint": finding.fingerprint,
                "created_at": finding.created_at,
                "updated_at": finding.updated_at,
                "description": finding.description,
                "file_path": finding.file_path,
                "line_number": finding.line_number,
                "raw_evidence": finding.raw_evidence,
                "snippet": finding.snippet,
            }
            for finding in findings
        ]

        insert_stmt = postgresql.insert(FindingModel).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["repository_id", "fingerprint"],
            set_={
                "last_seen_scan_run_id": insert_stmt.excluded.last_seen_scan_run_id,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(upsert_stmt)

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        """Return the number of `Finding`s whose `last_seen_scan_run_id == scan_run_id`.

        Powers the redefined `GET /scans/{id}` findings COUNT (Module 7 D5).
        """
        stmt = (
            select(func.count())
            .select_from(FindingModel)
            .where(FindingModel.last_seen_scan_run_id == scan_run_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        """Powers `GET /scans/{scan_run_id}/findings`."""
        stmt = (
            select(FindingModel)
            .where(FindingModel.last_seen_scan_run_id == scan_run_id)
            .order_by(FindingModel.created_at.desc(), FindingModel.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [finding_to_entity(model) for model in result.scalars().all()]

    async def list_findings(
        self,
        *,
        severity: FindingSeverity | None = None,
        status: FindingStatus | None = None,
        repository_id: uuid.UUID | None = None,
        scanner_type: ScannerType | None = None,
        limit: int,
        offset: int,
    ) -> list[Finding]:
        """Powers `GET /findings`. Joins to `ScanTaskModel` ONLY when
        `scanner_type` is supplied — `Finding` carries no denormalized
        scanner_type column, and the join key (`scan_task_id` -> PK) is
        indexed, but the cost is avoided entirely when the filter is unused.
        """
        stmt = select(FindingModel)
        if scanner_type is not None:
            stmt = stmt.join(ScanTaskModel, FindingModel.scan_task_id == ScanTaskModel.id).where(
                ScanTaskModel.scanner_type == scanner_type
            )
        if severity is not None:
            stmt = stmt.where(FindingModel.severity == severity)
        if status is not None:
            stmt = stmt.where(FindingModel.status == status)
        if repository_id is not None:
            stmt = stmt.where(FindingModel.repository_id == repository_id)

        stmt = (
            stmt.order_by(FindingModel.created_at.desc(), FindingModel.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [finding_to_entity(model) for model in result.scalars().all()]
