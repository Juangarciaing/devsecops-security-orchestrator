"""`SqlAlchemyFindingRepository.bulk_upsert_findings`/`count_by_last_seen_scan_run`
(Module 7 D4/D5) — live-Postgres coverage.

`bulk_upsert_findings` is Postgres-specific (`INSERT ... ON CONFLICT (repository_id,
fingerprint) DO UPDATE`), so it has NO SQLite/unit-level equivalent by design —
only the calling contract is unit-tested (`tests/unit/domain/test_ports.py`).
These tests prove the actual DB-atomic dedup semantics: unchanged fingerprint
re-scans advance `last_seen_scan_run_id` without creating a duplicate row and
without touching `status`; new fingerprints on a later scan create exactly one
new row; and two concurrent `bulk_upsert_findings` calls for the SAME
`(repository_id, fingerprint)` race safely — exactly one row survives, no crash
(the entire point of `ON CONFLICT` over a read-then-write TOCTOU check).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive columns


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme-scan",
        "name": f"widgets-{uuid.uuid4().hex[:8]}",
        "clone_url": "https://github.com/acme-scan/widgets.git",
        "default_branch": "main",
        "credential_ref": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


def _make_scan_run(repository_id: uuid.UUID, **overrides: object) -> ScanRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": repository_id,
        "status": ScanRunStatus.PENDING,
        "trigger": "manual",
        "commit_sha": "abc123",
        "ref": "abc123",
        "created_at": _NOW,
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


def _make_scan_task(scan_run_id: uuid.UUID, **overrides: object) -> ScanTask:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_run_id": scan_run_id,
        "scanner_type": ScannerType.SECRETS,
        "status": ScanTaskStatus.PENDING,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults.update(overrides)
    return ScanTask(**defaults)  # type: ignore[arg-type]


def _make_finding(scan_task_id: uuid.UUID, **overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": scan_task_id,
        "severity": FindingSeverity.HIGH,
        "rule_id": "generic-api-key",
        "title": "Hardcoded API key",
        "fingerprint": f"fp-{uuid.uuid4()}",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


async def _seed_repository_run_and_task(
    sessionmaker: async_sessionmaker[AsyncSession], **run_overrides: object
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create one `CodeRepository` + one `ScanRun` (on it) + one `ScanTask` (on
    that run). Returns `(repository_id, scan_run_id, scan_task_id)`."""
    async with sessionmaker() as session:
        code_repo = SqlAlchemyCodeRepositoryRepository(session)
        repository = await code_repo.create(_make_repository())
        await session.commit()
        repository_id = repository.id

    async with sessionmaker() as session:
        scan_run_repo = SqlAlchemyScanRunRepository(session)
        run = await scan_run_repo.create(_make_scan_run(repository_id, **run_overrides))
        await session.commit()
        scan_run_id = run.id

    async with sessionmaker() as session:
        scan_task_repo = SqlAlchemyScanTaskRepository(session)
        task = await scan_task_repo.create(_make_scan_task(scan_run_id))
        await session.commit()
        scan_task_id = task.id

    return repository_id, scan_run_id, scan_task_id


async def _bulk_upsert_first_scan_inserts_and_stamps_first_and_last_seen() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repository_id, scan_run_id, scan_task_id = await _seed_repository_run_and_task(sessionmaker)
        finding = _make_finding(scan_task_id)

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(repository_id, scan_run_id, [finding])
            await session.commit()

        async with sessionmaker() as session:
            stmt = select(FindingModel).where(
                FindingModel.repository_id == repository_id,
                FindingModel.fingerprint == finding.fingerprint,
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1
            assert rows[0].repository_id == repository_id
            assert rows[0].first_seen_scan_run_id == scan_run_id
            assert rows[0].last_seen_scan_run_id == scan_run_id
            assert rows[0].status == FindingStatus.OPEN

            finding_repo = SqlAlchemyFindingRepository(session)
            count = await finding_repo.count_by_last_seen_scan_run(scan_run_id)
            assert count == 1
    finally:
        await engine.dispose()


def test_bulk_upsert_first_scan_inserts_and_stamps_first_and_last_seen(
    migrated_schema: None,
) -> None:
    asyncio.run(_bulk_upsert_first_scan_inserts_and_stamps_first_and_last_seen())


async def _bulk_upsert_reseen_fingerprint_advances_last_seen_and_preserves_status() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repository_id, run1_id, task1_id = await _seed_repository_run_and_task(sessionmaker)

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            run2 = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run2_id = run2.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            task2 = await scan_task_repo.create(_make_scan_task(run2_id))
            await session.commit()
            task2_id = task2.id

        shared_fp = f"fp-shared-{uuid.uuid4()}"
        finding_v1 = _make_finding(task1_id, fingerprint=shared_fp)

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(repository_id, run1_id, [finding_v1])
            await session.commit()

        # Suppress the finding between the two scans — a re-scan must not
        # resurrect it to OPEN (status stays untouched on conflict). Uses a
        # raw UPDATE (not `finding_repo.update_status`) to isolate this test
        # to `bulk_upsert_findings`'s own behavior only.
        async with sessionmaker() as session:
            select_stmt = select(FindingModel.id).where(
                FindingModel.repository_id == repository_id,
                FindingModel.fingerprint == shared_fp,
            )
            original_id = (await session.execute(select_stmt)).scalar_one()
            await session.execute(
                update(FindingModel)
                .where(FindingModel.id == original_id)
                .values(status=FindingStatus.SUPPRESSED)
            )
            await session.commit()

        finding_v2 = _make_finding(task2_id, fingerprint=shared_fp)  # status defaults to OPEN
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(repository_id, run2_id, [finding_v2])
            await session.commit()

        async with sessionmaker() as session:
            stmt = select(FindingModel).where(
                FindingModel.repository_id == repository_id,
                FindingModel.fingerprint == shared_fp,
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 1
            assert rows[0].id == original_id
            assert rows[0].first_seen_scan_run_id == run1_id
            assert rows[0].last_seen_scan_run_id == run2_id
            assert rows[0].status == FindingStatus.SUPPRESSED

            finding_repo = SqlAlchemyFindingRepository(session)
            assert await finding_repo.count_by_last_seen_scan_run(run1_id) == 0
            assert await finding_repo.count_by_last_seen_scan_run(run2_id) == 1
    finally:
        await engine.dispose()


def test_bulk_upsert_reseen_fingerprint_advances_last_seen_and_preserves_status(
    migrated_schema: None,
) -> None:
    asyncio.run(_bulk_upsert_reseen_fingerprint_advances_last_seen_and_preserves_status())


async def _bulk_upsert_new_fingerprint_on_second_scan_adds_exactly_one_row() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repository_id, run1_id, task1_id = await _seed_repository_run_and_task(sessionmaker)

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            run2 = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run2_id = run2.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            task2 = await scan_task_repo.create(_make_scan_task(run2_id))
            await session.commit()
            task2_id = task2.id

        fp_a = f"fp-a-{uuid.uuid4()}"
        fp_b = f"fp-b-{uuid.uuid4()}"

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id, run1_id, [_make_finding(task1_id, fingerprint=fp_a)]
            )
            await session.commit()

        # Second scan re-observes fp_a AND introduces new fp_b, in one batch.
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run2_id,
                [
                    _make_finding(task2_id, fingerprint=fp_a),
                    _make_finding(task2_id, fingerprint=fp_b),
                ],
            )
            await session.commit()

        async with sessionmaker() as session:
            stmt = select(FindingModel).where(FindingModel.repository_id == repository_id)
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 2

            finding_repo = SqlAlchemyFindingRepository(session)
            assert await finding_repo.count_by_last_seen_scan_run(run1_id) == 0
            assert await finding_repo.count_by_last_seen_scan_run(run2_id) == 2
    finally:
        await engine.dispose()


def test_bulk_upsert_new_fingerprint_on_second_scan_adds_exactly_one_row(
    migrated_schema: None,
) -> None:
    asyncio.run(_bulk_upsert_new_fingerprint_on_second_scan_adds_exactly_one_row())


async def _bulk_upsert_concurrent_calls_same_fingerprint_are_race_safe() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            run_a = await scan_run_repo.create(_make_scan_run(repository_id))
            run_b = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_a_id, run_b_id = run_a.id, run_b.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            task_a = await scan_task_repo.create(_make_scan_task(run_a_id))
            task_b = await scan_task_repo.create(_make_scan_task(run_b_id))
            await session.commit()
            task_a_id, task_b_id = task_a.id, task_b.id

        shared_fp = f"fp-race-{uuid.uuid4()}"
        finding_a = _make_finding(task_a_id, fingerprint=shared_fp)
        finding_b = _make_finding(task_b_id, fingerprint=shared_fp)

        async def _upsert_via_own_connection(scan_run_id: uuid.UUID, finding: Finding) -> None:
            # Each coroutine opens its OWN session (own connection) so the two
            # `bulk_upsert_findings` calls genuinely execute concurrently at
            # the DB level, not serialized on one shared connection.
            async with sessionmaker() as session:
                finding_repo = SqlAlchemyFindingRepository(session)
                await finding_repo.bulk_upsert_findings(repository_id, scan_run_id, [finding])
                await session.commit()

        # Real concurrency: both INSERT ... ON CONFLICT statements race
        # against the SAME (repository_id, fingerprint) unique key. This is
        # exactly the scenario a read-then-write app-level check would
        # deadlock/duplicate on (TOCTOU) — ON CONFLICT resolves it atomically
        # via Postgres's speculative-insertion protocol instead.
        await asyncio.gather(
            _upsert_via_own_connection(run_a_id, finding_a),
            _upsert_via_own_connection(run_b_id, finding_b),
        )

        async with sessionmaker() as session:
            stmt = select(FindingModel).where(
                FindingModel.repository_id == repository_id,
                FindingModel.fingerprint == shared_fp,
            )
            rows = (await session.execute(stmt)).scalars().all()
            # Exactly one surviving row — no duplicate, no crash.
            assert len(rows) == 1
            assert rows[0].first_seen_scan_run_id in (run_a_id, run_b_id)
            assert rows[0].last_seen_scan_run_id in (run_a_id, run_b_id)
    finally:
        await engine.dispose()


def test_bulk_upsert_concurrent_calls_same_fingerprint_are_race_safe(
    migrated_schema: None,
) -> None:
    asyncio.run(_bulk_upsert_concurrent_calls_same_fingerprint_are_race_safe())
