"""Integration tests for `process_scan_task`'s REAL flow (Module 6 D1-D5):
checkout (init-container clone + `rev-parse HEAD`) -> resolve/persist the real
commit SHA -> run Gitleaks -> parse -> persist `Finding`s -> drive the
`ScanTask`/`ScanRun` state machine to `completed` (0..N real findings) or
`failed` (deterministic checkout/scan failure, no retry) or `completed` after
a transient Docker-daemon error retries and succeeds.

Uses `Task.apply()` — Celery's built-in eager/synchronous execution path — so
no live broker or running `celery worker` process is required. `container_runner`
and `docker_client` are test-only injection kwargs (production defaults to a
real `DockerContainerRunner`/`docker.from_env()`, mirroring Module 5's
`simulate_failure`/`fail_attempts` test-only-hook precedent): a `FakeContainerRunner`
(no real Docker socket needed here — that live proof is the mandatory live
e2e run, not this file) plus a `MagicMock` standing in for the low-level
`docker` client (volume create/get/remove + the chmod-prep container run,
never invoked via `ContainerRunnerPort` — same double `test_git_checkout.py`
already established).

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
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.container_runner_port import RunResult
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
from tests.fakes.fake_container_runner import FakeContainerRunner

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive columns
_CLONE_URL = "https://example.com/acme-scan/widgets.git"
_REF = "main"
_HEAD_SHA = "deadbeef1234"

_CLONE_OK = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)
_REV_PARSE_OK = RunResult(exit_code=0, stdout=f"{_HEAD_SHA}\n", stderr="", timed_out=False)
_GITLEAKS_CLEAN = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme-scan",
        "name": f"widgets-{uuid.uuid4().hex[:8]}",
        "clone_url": _CLONE_URL,
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
        "commit_sha": _REF,  # Module 5 placeholder; resolved to real SHA by GitCheckout
        "ref": _REF,
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


def test_process_scan_task_happy_path_persists_real_findings_and_resolved_sha(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    report = [
        {
            "RuleID": "stripe-access-token",
            "Description": "Stripe Access Token",
            "File": "config.py",
            "StartLine": 4,
            "Secret": "543736274dd00e9ca09b5942773b552873862520",
        },
        {
            "RuleID": "generic-api-key",
            "Description": "Generic API Key",
            "File": "settings.py",
            "StartLine": 9,
            "Secret": "some-other-secret",
        },
    ]
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False),
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.error_message is None
    assert run.status == ScanRunStatus.COMPLETED
    assert run.started_at is not None
    assert run.completed_at is not None
    assert run.commit_sha == _HEAD_SHA  # resolved real HEAD, not the "main" placeholder

    assert len(findings) == 2
    rule_ids = {f.rule_id for f in findings}  # type: ignore[attr-defined]
    assert rule_ids == {"stripe-access-token", "generic-api-key"}
    # Module 7 PR3 task 4.11: `findings.repository_id` is now `NOT NULL` at
    # the DB level — this still-legacy per-finding `create()` loop (the real
    # registry+`bulk_upsert_findings` re-wire is PR4, D6) must stamp
    # `repository_id` on every finding it persists, or every live scan would
    # start failing with a Postgres `NOT NULL` violation.
    assert all(f.repository_id == run.repository_id for f in findings)  # type: ignore[attr-defined]


def test_process_scan_task_clean_repo_completes_with_zero_findings(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(_CLONE_OK, _REV_PARSE_OK, _GITLEAKS_CLEAN)
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED  # zero findings is still success, not failed
    assert run.status == ScanRunStatus.COMPLETED
    assert run.commit_sha == _HEAD_SHA
    assert len(findings) == 0


def test_process_scan_task_marks_failed_on_checkout_failure_with_no_retry(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="fatal: Remote branch bad-ref not found",
            timed_out=False,
        )
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert "clone" in task.error_message
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0
    # deterministic checkout failure (D5) -> a SINGLE attempt, never retried
    assert len(fake_runner.calls) == 1


def test_process_scan_task_marks_failed_with_credential_resolution_reason_on_private_repo(
    migrated_schema: None,
) -> None:
    """Spec's "Private repo" scenario (`sdd/module-6-scanner-execution/spec`,
    "Checkout Failure Handling"): a clone failing because the repo requires
    auth this module doesn't support (public-repos-only, per the confirmed
    non-goal) MUST surface the specific literal reason "credential
    resolution not yet implemented" and land in `failed` via the SAME
    deterministic no-retry path as any other `CheckoutFailedError` (D5) —
    not the generic bad-ref message. `stderr` here is GitHub's real,
    unlocalized, server-controlled message (empirically confirmed via a
    live `GIT_TERMINAL_PROMPT=0 git clone` against a private/nonexistent
    GitHub repo — see `test_git_checkout.py`)."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr=(
                "remote: Repository not found.\n"
                "fatal: repository 'https://example.com/acme-scan/widgets.git/' not found\n"
            ),
            timed_out=False,
        )
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message == "credential resolution not yet implemented"
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0
    # deterministic checkout failure (D5) -> a SINGLE attempt, never retried
    assert len(fake_runner.calls) == 1


def test_process_scan_task_marks_failed_on_gitleaks_genuine_error_with_no_retry(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=1, stdout="", stderr="fatal: bad config", timed_out=False),
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0
    # exactly 3 attempts (clone + rev-parse + gitleaks), never retried afterward
    assert len(fake_runner.calls) == 3


def test_process_scan_task_marks_failed_on_gitleaks_timeout_with_no_retry(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=-1, stdout="", stderr="", timed_out=True),
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert "timed out" in task.error_message.lower()
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0


def test_process_scan_task_retries_transient_docker_error_then_completes(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()
    fake_runner.script(_CLONE_OK, _REV_PARSE_OK, _GITLEAKS_CLEAN)
    original_run = fake_runner.run
    call_count = {"n": 0}

    def _flaky_run(**kwargs: object) -> RunResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("docker daemon unreachable")
        return original_run(**kwargs)  # type: ignore[arg-type]

    fake_runner.run = _flaky_run  # type: ignore[method-assign]
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED
    assert task.error_message is None
    assert run.status == ScanRunStatus.COMPLETED
    assert run.commit_sha == _HEAD_SHA
    assert len(findings) == 0
    # the flaky first call plus the 3 real calls on the successful retry
    assert call_count["n"] == 4


def test_process_scan_task_exhausts_retries_on_persistent_transient_error_and_marks_failed(
    migrated_schema: None,
) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task())

    fake_runner = FakeContainerRunner()

    def _always_raise(**_: object) -> RunResult:
        raise RuntimeError("docker daemon unreachable")

    fake_runner.run = _always_raise  # type: ignore[method-assign]
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert "docker daemon unreachable" in task.error_message
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0
