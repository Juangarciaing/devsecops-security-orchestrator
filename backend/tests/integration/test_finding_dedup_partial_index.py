"""`SqlAlchemyFindingRepository.bulk_upsert_findings` — scan-target dedup
(dast-scanner design D2) — live-Postgres coverage.

Before D2, `findings.__table_args__` was `UniqueConstraint("repository_id",
"fingerprint")`. Once `repository_id` became nullable (PR2), Postgres treats
NULL as distinct in a unique constraint, so a target-subject finding would
never conflict with itself on re-scan — every re-scan would silently insert
a fresh row instead of deduping, and `first_seen_scan_run_id` would be wrong
forever. This test proves the fix: `bulk_upsert_findings` must route a
`ScanSubject(SCAN_TARGET, ...)` write through
`uq_findings_scan_target_fingerprint`, the partial unique index scoped to
`WHERE scan_target_id IS NOT NULL`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.domain.value_objects.scan_subject import ScanSubject, ScanSubjectKind
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.scan_target import ScanTargetModel
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    SqlAlchemyScanTargetRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive columns


def _make_scan_target(**overrides: object) -> ScanTarget:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "dedup-target",
        "target_url": f"https://{uuid.uuid4()}.test",
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return ScanTarget(**defaults)  # type: ignore[arg-type]


def _make_target_scan_run(scan_target_id: uuid.UUID, **overrides: object) -> ScanRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": None,
        "scan_target_id": scan_target_id,
        "status": ScanRunStatus.PENDING,
        "trigger": "manual",
        "commit_sha": None,
        "ref": None,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


def _make_scan_task(scan_run_id: uuid.UUID, **overrides: object) -> ScanTask:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_run_id": scan_run_id,
        "scanner_type": ScannerType.DAST,
        "status": ScanTaskStatus.PENDING,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults.update(overrides)
    return ScanTask(**defaults)  # type: ignore[arg-type]


def _make_target_finding(
    scan_task_id: uuid.UUID, scan_target_id: uuid.UUID, **overrides: object
) -> Finding:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": scan_task_id,
        "severity": FindingSeverity.HIGH,
        "rule_id": "zap-alert",
        "title": "Reflected XSS",
        "fingerprint": f"fp-{uuid.uuid4()}",
        "created_at": _NOW,
        "updated_at": _NOW,
        "scan_target_id": scan_target_id,
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


async def _seed_target_run_and_task(
    sessionmaker: async_sessionmaker[AsyncSession], scan_target_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as session:
        run = await SqlAlchemyScanRunRepository(session).create(
            _make_target_scan_run(scan_target_id)
        )
        await session.commit()
        run_id = run.id

    async with sessionmaker() as session:
        task = await SqlAlchemyScanTaskRepository(session).create(_make_scan_task(run_id))
        await session.commit()
        task_id = task.id

    return run_id, task_id


async def _rescanning_a_target_dedups_via_the_partial_target_index() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    # `migrated_schema` downgrades at teardown, which requires `ref`/
    # `commit_sha`/`repository_id` NOT NULL again — impossible while a
    # target-subject row (NULL ref/commit_sha/repository_id) survives. Clean
    # up this test's own rows unconditionally so the shared fixture's
    # downgrade keeps working, regardless of whether this test passes.
    target_id: uuid.UUID | None = None
    try:
        async with sessionmaker() as session:
            target = await SqlAlchemyScanTargetRepository(session).create(_make_scan_target())
            await session.commit()
            target_id = target.id

        shared_fp = f"fp-shared-{uuid.uuid4()}"
        subject = ScanSubject(ScanSubjectKind.SCAN_TARGET, target_id)

        run1_id, task1_id = await _seed_target_run_and_task(sessionmaker, target_id)
        async with sessionmaker() as session:
            await SqlAlchemyFindingRepository(session).bulk_upsert_findings(
                subject=subject,
                scan_run_id=run1_id,
                findings=[_make_target_finding(task1_id, target_id, fingerprint=shared_fp)],
            )
            await session.commit()

        run2_id, task2_id = await _seed_target_run_and_task(sessionmaker, target_id)
        async with sessionmaker() as session:
            await SqlAlchemyFindingRepository(session).bulk_upsert_findings(
                subject=subject,
                scan_run_id=run2_id,
                findings=[_make_target_finding(task2_id, target_id, fingerprint=shared_fp)],
            )
            await session.commit()

        async with sessionmaker() as session:
            stmt = select(FindingModel).where(
                FindingModel.scan_target_id == target_id,
                FindingModel.fingerprint == shared_fp,
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1, (
                "re-scanning the same target+fingerprint must dedup via "
                "uq_findings_scan_target_fingerprint, not insert a second row"
            )
            assert rows[0].first_seen_scan_run_id == run1_id
            assert rows[0].last_seen_scan_run_id == run2_id
    finally:
        if target_id is not None:
            async with sessionmaker() as session:
                await session.execute(
                    delete(ScanTargetModel).where(ScanTargetModel.id == target_id)
                )
                await session.commit()
        await engine.dispose()


def test_rescanning_a_target_dedups_via_the_partial_target_index(migrated_schema: None) -> None:
    asyncio.run(_rescanning_a_target_dedups_via_the_partial_target_index())
