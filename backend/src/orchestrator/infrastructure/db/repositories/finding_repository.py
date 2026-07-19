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
