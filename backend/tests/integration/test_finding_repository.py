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


# ---------------------------------------------------------------------------
# `update_status` / `create` — MissingGreenlet refresh fix (Module 8 PR1)
# ---------------------------------------------------------------------------


async def _update_status_persists_through_the_live_orm_path_without_missing_greenlet() -> None:
    """Spec: "Working `update_status` Persistence" — must be reachable
    through the REAL async SQLAlchemy ORM session (no fake/mock, no raw-SQL
    workaround), must not raise `MissingGreenlet`, and must persist both the
    new `status` and a newer `updated_at`.

    Root cause (design): `FindingModel.updated_at` has `onupdate=func.now()`.
    After `model.status = status; await flush()`, `updated_at` is expired
    server-side; `finding_to_entity(model)` reading it inside the SAME
    non-awaited call triggers a synchronous lazy refresh outside the awaited
    greenlet context. Using `bulk_upsert_findings` (the real production write
    path, not `create()`) to seed the row keeps this test isolated to
    `update_status` alone.
    """
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
            finding_repo = SqlAlchemyFindingRepository(session)
            before = await finding_repo.get_by_id(finding.id)
            assert before is not None

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            updated = await finding_repo.update_status(finding.id, FindingStatus.SUPPRESSED)
            await session.commit()

        assert updated.status == FindingStatus.SUPPRESSED
        assert updated.updated_at > before.updated_at

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            reread = await finding_repo.get_by_id(finding.id)
            assert reread is not None
            assert reread.status == FindingStatus.SUPPRESSED
            assert reread.updated_at > before.updated_at
    finally:
        await engine.dispose()


def test_update_status_persists_through_the_live_orm_path_without_missing_greenlet(
    migrated_schema: None,
) -> None:
    asyncio.run(_update_status_persists_through_the_live_orm_path_without_missing_greenlet())


async def _create_returns_an_entity_matching_the_persisted_row_after_refresh_fix() -> None:
    """Regression coverage for the defensive `refresh` fix in `create()`
    (design: `create()` carries the identical latent bug via
    `created_at`/`updated_at` server defaults, though no live caller hits it
    today since `Finding` always supplies explicit timestamps) — proves the
    fix doesn't change `create()`'s observable behavior."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repository_id, _, scan_task_id = await _seed_repository_run_and_task(sessionmaker)
        finding = _make_finding(scan_task_id, repository_id=repository_id)

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            created = await finding_repo.create(finding)
            await session.commit()

        assert created.id == finding.id
        assert created.status == FindingStatus.OPEN
        assert created.created_at == finding.created_at
        assert created.updated_at == finding.updated_at

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            reread = await finding_repo.get_by_id(finding.id)
            assert reread is not None
            assert reread.id == created.id
            assert reread.status == FindingStatus.OPEN
    finally:
        await engine.dispose()


def test_create_returns_an_entity_matching_the_persisted_row_after_refresh_fix(
    migrated_schema: None,
) -> None:
    asyncio.run(_create_returns_an_entity_matching_the_persisted_row_after_refresh_fix())


# ---------------------------------------------------------------------------
# `list_by_last_seen_scan_run` / `list_findings` (Module 8 PR2, task 1.6)
# ---------------------------------------------------------------------------


async def _list_by_last_seen_scan_run_returns_only_members_paginated() -> None:
    """Only findings whose `last_seen_scan_run_id == scan_run_id` are returned,
    most-recently-created first, respecting `limit`/`offset`."""
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

        # 3 findings attributed to run1, 1 to run2.
        run1_findings = [_make_finding(task1_id, fingerprint=f"fp-run1-{i}") for i in range(3)]
        run2_findings = [_make_finding(task2_id, fingerprint=f"fp-run2-{i}") for i in range(1)]

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(repository_id, run1_id, run1_findings)
            await finding_repo.bulk_upsert_findings(repository_id, run2_id, run2_findings)
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            page1 = await finding_repo.list_by_last_seen_scan_run(run1_id, limit=2, offset=0)
            page2 = await finding_repo.list_by_last_seen_scan_run(run1_id, limit=2, offset=2)
            run2_page = await finding_repo.list_by_last_seen_scan_run(run2_id, limit=20, offset=0)

        assert len(page1) == 2
        assert len(page2) == 1
        assert {f.id for f in page1} | {f.id for f in page2} == {f.id for f in run1_findings}
        assert len(run2_page) == 1
        assert run2_page[0].id == run2_findings[0].id
    finally:
        await engine.dispose()


def test_list_by_last_seen_scan_run_returns_only_members_paginated(
    migrated_schema: None,
) -> None:
    asyncio.run(_list_by_last_seen_scan_run_returns_only_members_paginated())


async def _list_findings_empty_result_when_nothing_matches() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            results = await finding_repo.list_findings(
                repository_id=uuid.uuid4(), limit=20, offset=0
            )
        assert results == []
    finally:
        await engine.dispose()


def test_list_findings_empty_result_when_nothing_matches(migrated_schema: None) -> None:
    asyncio.run(_list_findings_empty_result_when_nothing_matches())


async def _list_findings_combined_filters_and_scanner_type_join() -> None:
    """Seeds two `ScanTask`s of DIFFERENT `scanner_type` on the SAME repo, one
    finding on each with differing severity/status, then proves the
    severity+status+repository_id+scanner_type combination narrows to exactly
    the one matching row — verifying the conditional join is correct, not just
    present."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repository_id, run_id, secrets_task_id = await _seed_repository_run_and_task(sessionmaker)

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            sast_task = await scan_task_repo.create(
                _make_scan_task(run_id, scanner_type=ScannerType.SAST)
            )
            await session.commit()
            sast_task_id = sast_task.id

        secrets_finding = _make_finding(
            secrets_task_id,
            fingerprint="fp-secrets",
            severity=FindingSeverity.HIGH,
            status=FindingStatus.OPEN,
        )
        sast_finding = _make_finding(
            sast_task_id,
            fingerprint="fp-sast",
            severity=FindingSeverity.HIGH,
            status=FindingStatus.OPEN,
        )

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id, run_id, [secrets_finding, sast_finding]
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            # No scanner_type filter -> both match on severity/status/repository_id.
            both = await finding_repo.list_findings(
                severity=FindingSeverity.HIGH,
                status=FindingStatus.OPEN,
                repository_id=repository_id,
                limit=20,
                offset=0,
            )
            # scanner_type=SECRETS -> only the secrets-task finding.
            secrets_only = await finding_repo.list_findings(
                severity=FindingSeverity.HIGH,
                status=FindingStatus.OPEN,
                repository_id=repository_id,
                scanner_type=ScannerType.SECRETS,
                limit=20,
                offset=0,
            )

        assert {f.id for f in both} == {secrets_finding.id, sast_finding.id}
        assert [f.id for f in secrets_only] == [secrets_finding.id]
    finally:
        await engine.dispose()


def test_list_findings_combined_filters_and_scanner_type_join(migrated_schema: None) -> None:
    asyncio.run(_list_findings_combined_filters_and_scanner_type_join())


# ---------------------------------------------------------------------------
# `trend_counts_by_first_seen_run` / `open_counts_by_severity` (Module 12a PR1)
# ---------------------------------------------------------------------------


async def _seed_completed_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    repository_id: uuid.UUID,
    *,
    created_at: datetime,
    commit_sha: str = "abc123",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create one COMPLETED `ScanRun` (on `repository_id`) + one `ScanTask` on
    it. Returns `(scan_run_id, scan_task_id)`."""
    async with sessionmaker() as session:
        scan_run_repo = SqlAlchemyScanRunRepository(session)
        run = await scan_run_repo.create(
            _make_scan_run(
                repository_id,
                status=ScanRunStatus.COMPLETED,
                created_at=created_at,
                commit_sha=commit_sha,
            )
        )
        await session.commit()
        scan_run_id = run.id

    async with sessionmaker() as session:
        scan_task_repo = SqlAlchemyScanTaskRepository(session)
        task = await scan_task_repo.create(_make_scan_task(scan_run_id))
        await session.commit()
        scan_task_id = task.id

    return scan_run_id, scan_task_id


async def _trend_counts_three_runs_second_introduces_two_high_findings() -> None:
    """Spec Scenario: "Trend series for a scanned repository" — 3 completed
    scan runs, the 2nd introducing 2 HIGH findings -> 3 buckets in
    chronological order, 2nd bucket's introduced severities = {HIGH: 2}."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run1_id, _task1_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 1, 1)
        )
        run2_id, task2_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 1, 2)
        )
        run3_id, _task3_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 1, 3)
        )

        findings = [
            _make_finding(task2_id, fingerprint="fp-a", severity=FindingSeverity.HIGH),
            _make_finding(task2_id, fingerprint="fp-b", severity=FindingSeverity.HIGH),
        ]
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(repository_id, run2_id, findings)
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            buckets = await finding_repo.trend_counts_by_first_seen_run(repository_id)

        assert [b.scan_run_id for b in buckets] == [run1_id, run2_id, run3_id]
        assert buckets[0].severity_counts == {}
        assert buckets[1].severity_counts == {FindingSeverity.HIGH: 2}
        assert buckets[2].severity_counts == {}
    finally:
        await engine.dispose()


def test_trend_counts_three_runs_second_introduces_two_high_findings(
    migrated_schema: None,
) -> None:
    asyncio.run(_trend_counts_three_runs_second_introduces_two_high_findings())


async def _trend_counts_zero_completed_runs_returns_empty_list() -> None:
    """Spec Scenario: "Repository with no completed scans" -> empty list."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            buckets = await finding_repo.trend_counts_by_first_seen_run(repository_id)

        assert buckets == []
    finally:
        await engine.dispose()


def test_trend_counts_zero_completed_runs_returns_empty_list(migrated_schema: None) -> None:
    asyncio.run(_trend_counts_zero_completed_runs_returns_empty_list())


async def _trend_counts_reappeared_finding_stays_attributed_to_its_first_seen_run() -> None:
    """Edge case (design's cheap-semantics ceiling): a finding introduced on
    run1, ABSENT from run2's scan batch (a "gap"), then RE-OBSERVED on run3.
    `first_seen_scan_run_id` never advances on conflict (Module 7 D4), so the
    reappearance must NOT be double-counted as newly "introduced" on run3 —
    it stays attributed to run1 only, and run3's bucket for that severity
    stays at 0 even though the finding is once again present/open."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run1_id, task1_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 2, 1)
        )
        # run2: scanned, but this fingerprint is simply absent from its batch
        # (no per-run membership table exists to record the gap — Module 7's
        # dedup model is lossy by design for gaps).
        run2_id, _task2_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 2, 2)
        )
        run3_id, task3_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 2, 3)
        )

        shared_fp = "fp-reappear"
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run1_id,
                [_make_finding(task1_id, fingerprint=shared_fp, severity=FindingSeverity.CRITICAL)],
            )
            await session.commit()

        # run2's bulk_upsert batch simply never mentions `shared_fp` — this IS
        # the "gap": no row-level state records that it went missing.

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run3_id,
                [_make_finding(task3_id, fingerprint=shared_fp, severity=FindingSeverity.CRITICAL)],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            buckets = await finding_repo.trend_counts_by_first_seen_run(repository_id)
            open_counts = await finding_repo.open_counts_by_severity(repository_id)

        by_run = {b.scan_run_id: b.severity_counts for b in buckets}
        assert by_run[run1_id] == {FindingSeverity.CRITICAL: 1}
        assert by_run[run2_id] == {}
        assert by_run[run3_id] == {}  # reappearance is NOT a new "introduced" event
        # It IS still open right now — proves current_open is a real, separate
        # present-moment snapshot, never a stand-in for a historical bucket.
        assert open_counts == {FindingSeverity.CRITICAL: 1}
    finally:
        await engine.dispose()


def test_trend_counts_reappeared_finding_stays_attributed_to_its_first_seen_run(
    migrated_schema: None,
) -> None:
    asyncio.run(_trend_counts_reappeared_finding_stays_attributed_to_its_first_seen_run())


async def _trend_counts_scanner_type_filter_narrows_introduced_counts() -> None:
    """Spec Scenario: "Filtered by scanner_type" — findings introduced by
    both SECRETS and SEMGREP scans on the SAME run; filtering by
    `scanner_type=semgrep` narrows that bucket's counts to SEMGREP only,
    WITHOUT dropping the bucket itself (LEFT JOIN semantics preserved)."""
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
            run = await scan_run_repo.create(
                _make_scan_run(
                    repository_id, status=ScanRunStatus.COMPLETED, created_at=datetime(2026, 3, 1)
                )
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            secrets_task = await scan_task_repo.create(
                _make_scan_task(run_id, scanner_type=ScannerType.SECRETS)
            )
            semgrep_task = await scan_task_repo.create(
                _make_scan_task(run_id, scanner_type=ScannerType.SEMGREP)
            )
            await session.commit()
            secrets_task_id = secrets_task.id
            semgrep_task_id = semgrep_task.id

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run_id,
                [
                    _make_finding(
                        secrets_task_id, fingerprint="fp-secrets", severity=FindingSeverity.HIGH
                    ),
                    _make_finding(
                        semgrep_task_id, fingerprint="fp-semgrep", severity=FindingSeverity.HIGH
                    ),
                ],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            unfiltered = await finding_repo.trend_counts_by_first_seen_run(repository_id)
            semgrep_only = await finding_repo.trend_counts_by_first_seen_run(
                repository_id, scanner_type=ScannerType.SEMGREP
            )

        assert unfiltered[0].severity_counts == {FindingSeverity.HIGH: 2}
        # Bucket still present (LEFT JOIN preserved) but narrowed to 1.
        assert len(semgrep_only) == 1
        assert semgrep_only[0].scan_run_id == run_id
        assert semgrep_only[0].severity_counts == {FindingSeverity.HIGH: 1}
    finally:
        await engine.dispose()


def test_trend_counts_scanner_type_filter_narrows_introduced_counts(
    migrated_schema: None,
) -> None:
    asyncio.run(_trend_counts_scanner_type_filter_narrows_introduced_counts())


async def _trend_counts_scanner_type_filter_still_emits_empty_bucket_when_no_match() -> None:
    """Narrower edge case than the above: a run whose ONLY finding does NOT
    match the `scanner_type` filter must still appear as a bucket (count 0),
    never silently dropped — proves the filter lives in the join's ON clause,
    not a post-join WHERE that would eliminate the row (design's explicit
    "in ON, not WHERE" constraint)."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run_id, secrets_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 4, 1)
        )

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run_id,
                [_make_finding(secrets_task_id, fingerprint="fp-secrets-only")],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            semgrep_only = await finding_repo.trend_counts_by_first_seen_run(
                repository_id, scanner_type=ScannerType.SEMGREP
            )

        assert len(semgrep_only) == 1
        assert semgrep_only[0].scan_run_id == run_id
        assert semgrep_only[0].severity_counts == {}
    finally:
        await engine.dispose()


def test_trend_counts_scanner_type_filter_still_emits_empty_bucket_when_no_match(
    migrated_schema: None,
) -> None:
    asyncio.run(_trend_counts_scanner_type_filter_still_emits_empty_bucket_when_no_match())


async def _trend_counts_limit_caps_distinct_scan_runs_not_grouped_rows() -> None:
    """A run with 2 distinct severities produces 2 grouped rows for a SINGLE
    run. `limit` MUST cap the number of DISTINCT scan runs returned, never the
    number of (run, severity) grouped rows — otherwise a single busy run could
    silently consume the entire limit budget and truncate/drop later runs."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run1_id, task1_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 5, 1)
        )
        run2_id, _task2_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 5, 2)
        )

        # run1 alone introduces 2 DIFFERENT severities -> 2 grouped rows.
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run1_id,
                [
                    _make_finding(task1_id, fingerprint="fp-high", severity=FindingSeverity.HIGH),
                    _make_finding(task1_id, fingerprint="fp-low", severity=FindingSeverity.LOW),
                ],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            # limit=1 grouped ROW would only return part of run1's data if the
            # limit applied to grouped rows; limit=1 scan RUN must return
            # run1's COMPLETE bucket (both severities) and omit run2 entirely.
            buckets = await finding_repo.trend_counts_by_first_seen_run(repository_id, limit=1)

        assert len(buckets) == 1
        assert buckets[0].scan_run_id == run1_id
        assert buckets[0].severity_counts == {FindingSeverity.HIGH: 1, FindingSeverity.LOW: 1}
    finally:
        await engine.dispose()


def test_trend_counts_limit_caps_distinct_scan_runs_not_grouped_rows(
    migrated_schema: None,
) -> None:
    asyncio.run(_trend_counts_limit_caps_distinct_scan_runs_not_grouped_rows())


async def _open_counts_by_severity_returns_exact_present_moment_snapshot() -> None:
    """`open_counts_by_severity` is a plain present-moment snapshot
    (`status=open` GROUP BY severity) — suppressed findings are excluded."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run_id, task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 6, 1)
        )

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                run_id,
                [
                    _make_finding(
                        task_id, fingerprint="fp-open-high", severity=FindingSeverity.HIGH
                    ),
                    _make_finding(
                        task_id, fingerprint="fp-open-high-2", severity=FindingSeverity.HIGH
                    ),
                    _make_finding(task_id, fingerprint="fp-open-low", severity=FindingSeverity.LOW),
                ],
            )
            await session.commit()

        # Suppress one HIGH finding directly (isolating this test from
        # `update_status`'s own MissingGreenlet-fix coverage above).
        async with sessionmaker() as session:
            select_stmt = select(FindingModel.id).where(
                FindingModel.repository_id == repository_id,
                FindingModel.fingerprint == "fp-open-high-2",
            )
            suppressed_id = (await session.execute(select_stmt)).scalar_one()
            await session.execute(
                update(FindingModel)
                .where(FindingModel.id == suppressed_id)
                .values(status=FindingStatus.SUPPRESSED)
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            open_counts = await finding_repo.open_counts_by_severity(repository_id)

        assert open_counts == {FindingSeverity.HIGH: 1, FindingSeverity.LOW: 1}
    finally:
        await engine.dispose()


def test_open_counts_by_severity_returns_exact_present_moment_snapshot(
    migrated_schema: None,
) -> None:
    asyncio.run(_open_counts_by_severity_returns_exact_present_moment_snapshot())


# ---------------------------------------------------------------------------
# `diff_between_runs` (Module 12b PR1)
# ---------------------------------------------------------------------------


async def _diff_between_runs_partitions_added_resolved_and_carried_exactly() -> None:
    """Spec Scenarios: "Added/Resolved/Carried finding". Seeds an adjacent
    baseline + latest completed run pair:

    - `fp-added`: first_seen == latest -> ADDED only.
    - `fp-resolved`: first_seen == baseline, last_seen == baseline (never
      re-observed on latest) -> RESOLVED only.
    - `fp-carried`: first_seen == baseline, last_seen == latest (re-observed
      on latest, introduced before it) -> CARRIED only.

    Proves the three returned sets are pairwise disjoint (not merely
    asserted in prose) by checking id-set intersections are empty.
    """
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        baseline_id, baseline_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 1)
        )
        latest_id, latest_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 2)
        )

        # fp-resolved and fp-carried both introduced at baseline.
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                baseline_id,
                [
                    _make_finding(baseline_task_id, fingerprint="fp-resolved"),
                    _make_finding(baseline_task_id, fingerprint="fp-carried"),
                ],
            )
            await session.commit()

        # Latest run re-observes fp-carried (advances last_seen) and
        # introduces a brand-new fp-added. fp-resolved is simply absent from
        # this batch -> its last_seen stays pinned at baseline.
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                latest_id,
                [
                    _make_finding(latest_task_id, fingerprint="fp-carried"),
                    _make_finding(latest_task_id, fingerprint="fp-added"),
                ],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            diff = await finding_repo.diff_between_runs(repository_id, latest_id, baseline_id)

        added_fps = {f.fingerprint for f in diff.added}
        resolved_fps = {f.fingerprint for f in diff.resolved}
        carried_fps = {f.fingerprint for f in diff.carried}

        assert added_fps == {"fp-added"}
        assert resolved_fps == {"fp-resolved"}
        assert carried_fps == {"fp-carried"}

        # Disjointness proof: pairwise intersections on id, not just fingerprint.
        added_ids = {f.id for f in diff.added}
        resolved_ids = {f.id for f in diff.resolved}
        carried_ids = {f.id for f in diff.carried}
        assert added_ids & resolved_ids == set()
        assert added_ids & carried_ids == set()
        assert resolved_ids & carried_ids == set()
    finally:
        await engine.dispose()


def test_diff_between_runs_partitions_added_resolved_and_carried_exactly(
    migrated_schema: None,
) -> None:
    asyncio.run(_diff_between_runs_partitions_added_resolved_and_carried_exactly())


async def _diff_between_runs_reobserved_finding_lands_in_carried_never_added() -> None:
    """A finding whose `first_seen_scan_run_id` is stable at baseline (never
    advances on conflict, Module 7 D4) must classify as CARRIED — never
    ADDED — even though it was just re-upserted on the latest run."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        baseline_id, baseline_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 5)
        )
        latest_id, latest_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 6)
        )

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                baseline_id,
                [_make_finding(baseline_task_id, fingerprint="fp-reobserved")],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                latest_id,
                [_make_finding(latest_task_id, fingerprint="fp-reobserved")],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            diff = await finding_repo.diff_between_runs(repository_id, latest_id, baseline_id)

        assert {f.fingerprint for f in diff.carried} == {"fp-reobserved"}
        assert diff.added == []
        assert diff.resolved == []
    finally:
        await engine.dispose()


def test_diff_between_runs_reobserved_finding_lands_in_carried_never_added(
    migrated_schema: None,
) -> None:
    asyncio.run(_diff_between_runs_reobserved_finding_lands_in_carried_never_added())


async def _diff_between_runs_latest_zero_findings_added_and_carried_empty_resolved_populated() -> (
    None
):
    """Spec Scenario: "Latest run found nothing" — baseline has open
    findings, latest introduces nothing -> `resolved` lists the baseline
    findings, `added`/`carried` are empty."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        baseline_id, baseline_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 8)
        )
        latest_id, _latest_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 9)
        )

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                baseline_id,
                [
                    _make_finding(baseline_task_id, fingerprint="fp-baseline-1"),
                    _make_finding(baseline_task_id, fingerprint="fp-baseline-2"),
                ],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            diff = await finding_repo.diff_between_runs(repository_id, latest_id, baseline_id)

        assert {f.fingerprint for f in diff.resolved} == {"fp-baseline-1", "fp-baseline-2"}
        assert diff.added == []
        assert diff.carried == []
    finally:
        await engine.dispose()


def test_diff_between_runs_latest_zero_findings_added_and_carried_empty_resolved_populated(
    migrated_schema: None,
) -> None:
    asyncio.run(
        _diff_between_runs_latest_zero_findings_added_and_carried_empty_resolved_populated()
    )


async def _diff_between_runs_excludes_finding_resolved_before_baseline() -> None:
    """A finding whose `last_seen_scan_run_id` predates `baseline_id` (already
    gone before the delta window) MUST appear in none of the three sets —
    never forced into RESOLVED/CARRIED/ADDED."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        ancient_id, ancient_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 1)
        )
        baseline_id, _baseline_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 2)
        )
        latest_id, _latest_task_id = await _seed_completed_run(
            sessionmaker, repository_id, created_at=datetime(2026, 7, 3)
        )

        # This finding's last_seen is pinned at the ancient run (predates
        # baseline) — it vanished before the diff's window even opened.
        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            await finding_repo.bulk_upsert_findings(
                repository_id,
                ancient_id,
                [_make_finding(ancient_task_id, fingerprint="fp-long-gone")],
            )
            await session.commit()

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)
            diff = await finding_repo.diff_between_runs(repository_id, latest_id, baseline_id)

        all_fps = (
            {f.fingerprint for f in diff.added}
            | {f.fingerprint for f in diff.resolved}
            | {f.fingerprint for f in diff.carried}
        )
        assert "fp-long-gone" not in all_fps
    finally:
        await engine.dispose()


def test_diff_between_runs_excludes_finding_resolved_before_baseline(
    migrated_schema: None,
) -> None:
    asyncio.run(_diff_between_runs_excludes_finding_resolved_before_baseline())
