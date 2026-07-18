"""Integration tests for `process_scan_task` (D2, D5): drives the
`ScanRun`/`ScanTask` state machine to `completed` (happy path) or `failed`
(retries exhausted), writes exactly one placeholder `Finding`, and exercises
the manual retry/backoff loop via the test-only `fail_attempts` hook.

Uses `Task.apply()` — Celery's built-in eager/synchronous execution path — so
no live broker or running `celery worker` process is required. When the task
calls `self.retry()`, `Task.apply()` catches the resulting `Retry` exception
and replays the task immediately (no real `countdown` delay), which keeps
these tests fast and fully deterministic.

`process_scan_task` is imported LAZILY inside each test function, after the
`migrated_schema`/`db_env` fixture has populated `Settings`' required env
vars via monkeypatch — `workers/celery_app.py` resolves `Settings()` eagerly
at import time (the standard Celery `-A module` requirement), so importing
it at module top-level here would fail collection whenever no `.env` is
present, exactly the constraint `tests/unit/workers/test_celery_app.py`
already works around.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import (
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


async def _seed_pending_task() -> tuple[uuid.UUID, uuid.UUID]:
    """Create a `CodeRepository` + pending `ScanRun`/`ScanTask`; return (task_id, run_id)."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = await SqlAlchemyCodeRepositoryRepository(session).create(
                _make_repository()
            )
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            run = await SqlAlchemyScanRunRepository(session).create(_make_scan_run(repository_id))
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).create(_make_scan_task(run_id))
            await session.commit()
            task_id = task.id

        return task_id, run_id
    finally:
        await engine.dispose()


async def _load_state(
    scan_task_id: uuid.UUID, scan_run_id: uuid.UUID
) -> tuple[ScanTask, ScanRun, list[object]]:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).get_by_id(scan_task_id)
            run = await SqlAlchemyScanRunRepository(session).get_by_id(scan_run_id)
            findings = await SqlAlchemyFindingRepository(session).list_by_scan_task(scan_task_id)
            assert task is not None
            assert run is not None
            return task, run, list(findings)
    finally:
        await engine.dispose()


def test_process_scan_task_happy_path_writes_one_finding_and_completes(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    result = process_scan_task.apply(args=(str(task_id),))
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.error_message is None
    assert run.status == ScanRunStatus.COMPLETED
    assert run.started_at is not None
    assert run.completed_at is not None

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "placeholder"
    assert finding.fingerprint == hashlib.sha256(f"{task_id}:placeholder".encode()).hexdigest()


def test_process_scan_task_retries_then_completes_when_failures_below_max(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import MAX_RETRIES, process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())
    assert 0 < 2 < MAX_RETRIES

    result = process_scan_task.apply(
        args=(str(task_id),), kwargs={"simulate_failure": True, "fail_attempts": 2}
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED
    assert task.error_message is None
    assert run.status == ScanRunStatus.COMPLETED
    assert len(findings) == 1


def test_process_scan_task_exhausts_retries_and_marks_terminal_failed(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    result = process_scan_task.apply(args=(str(task_id),), kwargs={"simulate_failure": True})
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert task.started_at is not None
    assert task.completed_at is not None
    assert run.status == ScanRunStatus.FAILED
    assert run.completed_at is not None
    assert len(findings) == 0
