"""Contract tests for `SqlAlchemyScanRunRepository`, `SqlAlchemyScanTaskRepository`,
and `SqlAlchemyFindingRepository` against a live Postgres.

DDL-level constraints (unique identity, cascade) are already proven in
`test_unique_constraints.py` / `test_cascade_delete.py`; these tests instead
prove the three adapters correctly implement their ports: round-trip through
the mappers, `update_status` mutating status, and `find_active_task` (D3)
matching only in-flight (`pending`/`running`) tasks scoped to
`(repository_id, commit_sha, scanner_type)`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    ScanRunNotFoundError,
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    ScanTaskNotFoundError,
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


def _make_finding(
    scan_task_id: uuid.UUID, repository_id: uuid.UUID, **overrides: object
) -> Finding:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": scan_task_id,
        "repository_id": repository_id,
        "severity": FindingSeverity.INFO,
        "rule_id": "placeholder",
        "title": "Placeholder finding",
        "fingerprint": f"fp-{uuid.uuid4()}",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SqlAlchemyScanRunRepository
# ---------------------------------------------------------------------------


async def _scan_run_create_get_list_update_roundtrip() -> None:
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
            created = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_id = created.id

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)

            by_id = await scan_run_repo.get_by_id(run_id)
            assert by_id is not None
            assert by_id.repository_id == repository_id
            assert by_id.status == ScanRunStatus.PENDING
            assert by_id.trigger == "manual"

            missing = await scan_run_repo.get_by_id(uuid.uuid4())
            assert missing is None

            by_repo = await scan_run_repo.list_by_repository(repository_id)
            assert any(r.id == run_id for r in by_repo)

            updated = await scan_run_repo.update_status(run_id, ScanRunStatus.RUNNING)
            await session.commit()
            assert updated.status == ScanRunStatus.RUNNING

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            persisted = await scan_run_repo.get_by_id(run_id)
            assert persisted is not None
            assert persisted.status == ScanRunStatus.RUNNING
    finally:
        await engine.dispose()


def test_scan_run_create_get_list_and_update_status(migrated_schema: None) -> None:
    asyncio.run(_scan_run_create_get_list_update_roundtrip())


async def _scan_run_update_status_raises_not_found() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            with pytest.raises(ScanRunNotFoundError):
                await scan_run_repo.update_status(uuid.uuid4(), ScanRunStatus.RUNNING)
    finally:
        await engine.dispose()


def test_scan_run_update_status_raises_not_found_for_missing_id(migrated_schema: None) -> None:
    asyncio.run(_scan_run_update_status_raises_not_found())


async def _scan_run_update_status_persists_started_and_completed_at() -> None:
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
            run = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            started = await scan_run_repo.update_status(
                run_id, ScanRunStatus.RUNNING, started_at=_NOW
            )
            await session.commit()
            assert started.started_at == _NOW
            assert started.completed_at is None

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            completed = await scan_run_repo.update_status(
                run_id, ScanRunStatus.COMPLETED, completed_at=_NOW
            )
            await session.commit()
            # started_at set by the previous call MUST survive an update_status
            # call that only passes completed_at (D2/D5 worker semantics).
            assert completed.started_at == _NOW
            assert completed.completed_at == _NOW
    finally:
        await engine.dispose()


def test_scan_run_update_status_persists_started_and_completed_at(
    migrated_schema: None,
) -> None:
    asyncio.run(_scan_run_update_status_persists_started_and_completed_at())


async def _scan_run_list_paginated_orders_newest_first_and_respects_limit_offset() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        run_ids: list[uuid.UUID] = []
        for i in range(3):
            async with sessionmaker() as session:
                scan_run_repo = SqlAlchemyScanRunRepository(session)
                created = await scan_run_repo.create(
                    _make_scan_run(
                        repository_id,
                        commit_sha=f"page-{i}",
                        ref=f"page-{i}",
                        created_at=datetime(2026, 1, 1 + i),
                    )
                )
                await session.commit()
                run_ids.append(created.id)

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)

            first_page = await scan_run_repo.list_paginated(limit=2, offset=0)
            assert [r.id for r in first_page] == [run_ids[2], run_ids[1]]

            second_page = await scan_run_repo.list_paginated(limit=2, offset=2)
            assert [r.id for r in second_page] == [run_ids[0]]
    finally:
        await engine.dispose()


def test_scan_run_list_paginated_orders_newest_first_and_respects_limit_offset(
    migrated_schema: None,
) -> None:
    asyncio.run(_scan_run_list_paginated_orders_newest_first_and_respects_limit_offset())


async def _scan_run_update_commit_sha_persists_resolved_sha() -> None:
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
            # `commit_sha` at creation is a placeholder branch/ref name (Module 5) —
            # `GitCheckout` resolves the real HEAD SHA and this persists it back.
            created = await scan_run_repo.create(
                _make_scan_run(repository_id, commit_sha="main", ref="main")
            )
            await session.commit()
            run_id = created.id

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            resolved_sha = "a" * 40
            updated = await scan_run_repo.update_commit_sha(run_id, resolved_sha)
            await session.commit()
            assert updated.commit_sha == resolved_sha
            # `ref` (the original branch name) is untouched — only `commit_sha`
            # is overwritten with the resolved SHA.
            assert updated.ref == "main"

        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            persisted = await scan_run_repo.get_by_id(run_id)
            assert persisted is not None
            assert persisted.commit_sha == resolved_sha
    finally:
        await engine.dispose()


def test_scan_run_update_commit_sha_persists_resolved_sha(migrated_schema: None) -> None:
    asyncio.run(_scan_run_update_commit_sha_persists_resolved_sha())


async def _scan_run_update_commit_sha_raises_not_found() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_repo = SqlAlchemyScanRunRepository(session)
            with pytest.raises(ScanRunNotFoundError):
                await scan_run_repo.update_commit_sha(uuid.uuid4(), "b" * 40)
    finally:
        await engine.dispose()


def test_scan_run_update_commit_sha_raises_not_found_for_missing_id(
    migrated_schema: None,
) -> None:
    asyncio.run(_scan_run_update_commit_sha_raises_not_found())


# ---------------------------------------------------------------------------
# SqlAlchemyScanTaskRepository
# ---------------------------------------------------------------------------


async def _scan_task_create_get_list_update_roundtrip() -> None:
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
            run = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            created = await scan_task_repo.create(_make_scan_task(run_id))
            await session.commit()
            task_id = created.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)

            by_id = await scan_task_repo.get_by_id(task_id)
            assert by_id is not None
            assert by_id.scan_run_id == run_id
            assert by_id.scanner_type == ScannerType.SECRETS
            assert by_id.status == ScanTaskStatus.PENDING

            missing = await scan_task_repo.get_by_id(uuid.uuid4())
            assert missing is None

            by_run = await scan_task_repo.list_by_scan_run(run_id)
            assert any(t.id == task_id for t in by_run)

            updated = await scan_task_repo.update_status(task_id, ScanTaskStatus.COMPLETED)
            await session.commit()
            assert updated.status == ScanTaskStatus.COMPLETED
    finally:
        await engine.dispose()


def test_scan_task_create_get_list_and_update_status(migrated_schema: None) -> None:
    asyncio.run(_scan_task_create_get_list_update_roundtrip())


async def _scan_task_update_status_raises_not_found() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            with pytest.raises(ScanTaskNotFoundError):
                await scan_task_repo.update_status(uuid.uuid4(), ScanTaskStatus.COMPLETED)
    finally:
        await engine.dispose()


def test_scan_task_update_status_raises_not_found_for_missing_id(migrated_schema: None) -> None:
    asyncio.run(_scan_task_update_status_raises_not_found())


async def _scan_task_update_status_persists_timestamps_and_error_message() -> None:
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
            run = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            created = await scan_task_repo.create(_make_scan_task(run_id))
            await session.commit()
            task_id = created.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            started = await scan_task_repo.update_status(
                task_id, ScanTaskStatus.RUNNING, started_at=_NOW
            )
            await session.commit()
            assert started.started_at == _NOW

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            failed = await scan_task_repo.update_status(
                task_id,
                ScanTaskStatus.FAILED,
                completed_at=_NOW,
                error_message="simulated transient failure",
            )
            await session.commit()
            # started_at set earlier MUST survive an update_status call that
            # only passes completed_at/error_message (D2/D5 worker semantics).
            assert failed.started_at == _NOW
            assert failed.completed_at == _NOW
            assert failed.error_message == "simulated transient failure"
    finally:
        await engine.dispose()


def test_scan_task_update_status_persists_timestamps_and_error_message(
    migrated_schema: None,
) -> None:
    asyncio.run(_scan_task_update_status_persists_timestamps_and_error_message())


# ---------------------------------------------------------------------------
# find_active_task (D3)
# ---------------------------------------------------------------------------


async def _find_active_task_returns_none_when_no_task_exists() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            code_repo = SqlAlchemyCodeRepositoryRepository(session)
            repository = await code_repo.create(_make_repository())
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            active = await scan_task_repo.find_active_task(
                repository_id, "abc123", ScannerType.SECRETS
            )
            assert active is None
    finally:
        await engine.dispose()


def test_find_active_task_returns_none_when_no_task_exists(migrated_schema: None) -> None:
    asyncio.run(_find_active_task_returns_none_when_no_task_exists())


async def _find_active_task_matches_pending_and_running(status: ScanTaskStatus) -> None:
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
                _make_scan_run(repository_id, commit_sha="deadbeef", ref="deadbeef")
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            task = await scan_task_repo.create(
                _make_scan_task(run_id, scanner_type=ScannerType.SECRETS, status=status)
            )
            await session.commit()
            task_id = task.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            active = await scan_task_repo.find_active_task(
                repository_id, "deadbeef", ScannerType.SECRETS
            )
            assert active is not None
            assert active.id == task_id
            assert active.status == status
    finally:
        await engine.dispose()


def test_find_active_task_returns_pending_task(migrated_schema: None) -> None:
    asyncio.run(_find_active_task_matches_pending_and_running(ScanTaskStatus.PENDING))


def test_find_active_task_returns_running_task(migrated_schema: None) -> None:
    asyncio.run(_find_active_task_matches_pending_and_running(ScanTaskStatus.RUNNING))


async def _find_active_task_ignores_completed_task() -> None:
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
                _make_scan_run(repository_id, commit_sha="feedface", ref="feedface")
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            await scan_task_repo.create(
                _make_scan_task(
                    run_id, scanner_type=ScannerType.SECRETS, status=ScanTaskStatus.COMPLETED
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            active = await scan_task_repo.find_active_task(
                repository_id, "feedface", ScannerType.SECRETS
            )
            assert active is None
    finally:
        await engine.dispose()


def test_find_active_task_ignores_completed_task(migrated_schema: None) -> None:
    asyncio.run(_find_active_task_ignores_completed_task())


async def _find_active_task_filters_by_scanner_type() -> None:
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
                _make_scan_run(repository_id, commit_sha="c0ffee", ref="c0ffee")
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            await scan_task_repo.create(_make_scan_task(run_id, scanner_type=ScannerType.SAST))
            await session.commit()

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            active = await scan_task_repo.find_active_task(
                repository_id, "c0ffee", ScannerType.SECRETS
            )
            assert active is None
    finally:
        await engine.dispose()


def test_find_active_task_filters_by_scanner_type(migrated_schema: None) -> None:
    asyncio.run(_find_active_task_filters_by_scanner_type())


# ---------------------------------------------------------------------------
# SqlAlchemyFindingRepository
# ---------------------------------------------------------------------------


async def _finding_create_count_and_list_roundtrip() -> None:
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
            run = await scan_run_repo.create(_make_scan_run(repository_id))
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            task = await scan_task_repo.create(_make_scan_task(run_id))
            await session.commit()
            task_id = task.id

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)

            zero_count = await finding_repo.count_by_scan_task(task_id)
            assert zero_count == 0

            created = await finding_repo.create(_make_finding(task_id, repository_id))
            await session.commit()
            finding_id = created.id

        async with sessionmaker() as session:
            finding_repo = SqlAlchemyFindingRepository(session)

            by_id = await finding_repo.get_by_id(finding_id)
            assert by_id is not None
            assert by_id.scan_task_id == task_id
            assert by_id.repository_id == repository_id
            assert by_id.rule_id == "placeholder"

            one_count = await finding_repo.count_by_scan_task(task_id)
            assert one_count == 1

            by_task = await finding_repo.list_by_scan_task(task_id)
            assert len(by_task) == 1
            assert by_task[0].id == finding_id
    finally:
        await engine.dispose()


def test_finding_create_count_and_list_by_scan_task(migrated_schema: None) -> None:
    asyncio.run(_finding_create_count_and_list_roundtrip())
