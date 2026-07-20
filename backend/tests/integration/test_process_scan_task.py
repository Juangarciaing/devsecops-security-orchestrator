"""Integration tests for `process_scan_task`'s REAL flow (Module 6 D1-D5,
Module 7 D6): checkout (init-container clone + `rev-parse HEAD`) -> resolve/
persist the real commit SHA -> resolve the adapter via
`registry.get_adapter(scanner_type, ...)` -> run Gitleaks -> parse ->
`bulk_upsert_findings` (cross-run dedup on `(repository_id, fingerprint)`) ->
drive the `ScanTask`/`ScanRun` state machine to `completed` (0..N real
findings) or `failed` (deterministic checkout/scan/registry-lookup failure, no
retry) or `completed` after a transient Docker-daemon error retries and
succeeds.

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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import (
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


async def _seed_pending_task(**scan_task_overrides: object) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a `CodeRepository` + pending `ScanRun`/`ScanTask`; return (task_id, run_id).

    `**scan_task_overrides` (e.g. `scanner_type=ScannerType.SAST`) are passed
    through to `_make_scan_task`.
    """
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
            task = await SqlAlchemyScanTaskRepository(session).create(
                _make_scan_task(run_id, **scan_task_overrides)
            )
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


async def _seed_repository() -> uuid.UUID:
    """Create one `CodeRepository` (no run/task yet). Returns its id.

    Used by the re-scan/dedup test below, which needs MULTIPLE `ScanRun`s +
    `ScanTask`s attached to the SAME repository — `_seed_pending_task`
    creates its own repository per call, which would defeat the whole point
    (dedup is scoped to `(repository_id, fingerprint)`, Module 7 D4).
    """
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = await SqlAlchemyCodeRepositoryRepository(session).create(
                _make_repository()
            )
            await session.commit()
            return repository.id
    finally:
        await engine.dispose()


async def _seed_pending_task_for_repository(
    repository_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a pending `ScanRun`/`ScanTask` on an EXISTING `repository_id`.

    Returns `(task_id, run_id)`.
    """
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
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


async def _load_findings_for_repository(repository_id: uuid.UUID) -> list[FindingModel]:
    """Direct model query (bypasses `FindingPort`, which has no "list all
    findings for a repository" method) — needed to prove NO duplicate row
    was created across re-scans, which `list_by_scan_task` cannot show: on a
    conflict, `bulk_upsert_findings` does NOT update `scan_task_id`, so a
    re-seen `Finding` stays attributed to whichever `ScanTask` first inserted
    it (Module 7 D4)."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            stmt = select(FindingModel).where(FindingModel.repository_id == repository_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _suppress_finding(finding_id: uuid.UUID) -> None:
    """Raw `UPDATE` (not `finding_repo.update_status` — see Module 7 PR3
    apply-progress "Issues Found": that method has a pre-existing,
    unreachable `MissingGreenlet` bug, out of this batch's scope) to simulate
    a triage action between scans."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            await session.execute(
                update(FindingModel)
                .where(FindingModel.id == finding_id)
                .values(status=FindingStatus.SUPPRESSED)
            )
            await session.commit()
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


def test_process_scan_task_marks_failed_on_pip_audit_genuine_error_with_no_retry(
    migrated_schema: None,
) -> None:
    """Module 11 D7: `PipAuditFailedError` must be classified the SAME as
    `CheckoutFailedError`/`GitleaksFailedError` — a single deterministic
    attempt straight to `failed`, bypassing Module 5's 6x transient
    retry/backoff loop entirely. Mirrors
    `test_process_scan_task_marks_failed_on_gitleaks_genuine_error_with_no_retry`
    exactly, swapping the scanner and its genuine-failure `RunResult` shape
    (malformed/empty pip-audit stdout, D4)."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task(scanner_type=ScannerType.SCA))

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),  # probe: manifest present
        RunResult(exit_code=1, stdout="", stderr="pip-audit crashed", timed_out=False),
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
    # exactly 4 attempts (clone + rev-parse + probe + pip-audit), never retried
    assert len(fake_runner.calls) == 4


def test_process_scan_task_marks_failed_on_sast_genuine_error_with_no_retry(
    migrated_schema: None,
) -> None:
    """Module 11 D5 (PR2): `SastFailedError` must be classified the SAME as
    `CheckoutFailedError`/`GitleaksFailedError`/`PipAuditFailedError` — a
    single deterministic attempt straight to `failed`, bypassing Module 5's
    5x transient retry/backoff loop entirely. Mirrors
    `test_process_scan_task_marks_failed_on_gitleaks_genuine_error_with_no_retry`
    exactly, swapping the scanner and its genuine-failure `RunResult` shape
    (no `{` in stdout at all -> `SastFailedError` from `AstSastAdapter.parse()`,
    D2)."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task(scanner_type=ScannerType.SAST))

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=1, stdout="", stderr="sast-scanner crashed", timed_out=False),
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
    # exactly 3 attempts (clone + rev-parse + sast-scan), never retried afterward
    assert len(fake_runner.calls) == 3


def test_process_scan_task_marks_failed_on_semgrep_genuine_error_with_no_retry(
    migrated_schema: None,
) -> None:
    """Module 11 D8 (Semgrep, PR3): `SemgrepFailedError` must be classified
    the SAME as `CheckoutFailedError`/`GitleaksFailedError`/
    `PipAuditFailedError`/`SastFailedError` — a single deterministic attempt
    straight to `failed`, bypassing Module 5's 5x transient retry/backoff
    loop entirely. Mirrors
    `test_process_scan_task_marks_failed_on_sast_genuine_error_with_no_retry`
    exactly, swapping the scanner and its genuine-failure `RunResult` shape
    (empty stdout -> `SemgrepFailedError` from `SemgrepAdapter.parse()`,
    D6)."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task(scanner_type=ScannerType.SEMGREP))

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=1, stdout="", stderr="semgrep crashed", timed_out=False),
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
    # exactly 3 attempts (clone + rev-parse + semgrep-scan), never retried afterward
    assert len(fake_runner.calls) == 3


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


def test_process_scan_task_marks_failed_when_scanner_type_has_no_registered_adapter(
    migrated_schema: None,
) -> None:
    """Module 7 D6 proof: the adapter is now resolved via
    `registry.get_adapter(task.scanner_type, ...)`, NOT a hardcoded
    `GitleaksAdapter(...)`. A `ScanTask` whose `scanner_type` has no
    registration (only `SECRETS`/`SCA`/`SAST` are registered as of Module 11
    PR1 — `DAST` still is not) must fail with `UnregisteredScannerError`'s
    message — which is only reachable if `scanner_type` is genuinely
    consulted before any checkout/scan attempt. Before this PR (hardcoded
    `GitleaksAdapter`), `scanner_type` was never read at all and this
    scenario would instead fail on the FIRST scripted container call (or
    crash with an empty-script error) with a completely different message.
    """
    from orchestrator.workers.tasks.process_scan import process_scan_task

    task_id, run_id = asyncio.run(_seed_pending_task(scanner_type=ScannerType.DAST))

    # No container calls should happen at all: `get_adapter` raises before
    # `GitCheckout.checkout()` (or `adapter.scan()`) is ever reached.
    fake_runner = FakeContainerRunner()
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert "no adapter registered for scanner type" in task.error_message
    assert "dast" in task.error_message.lower()
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0
    assert len(fake_runner.calls) == 0


def test_process_scan_task_second_and_third_scans_of_same_repo_dedupe_and_preserve_status(
    migrated_schema: None,
) -> None:
    """Module 7 D4/D6 end-to-end proof (the actual point of this module) via
    the REAL `process_scan_task` flow (not just `bulk_upsert_findings` in
    isolation, which `test_finding_repository.py` already covers):

    1. First scan of a repo finds one secret -> exactly 1 `Finding`,
       `first_seen == last_seen == run1`.
    2. Second scan of the SAME repo (same secret re-observed + one brand-new
       secret) -> still exactly 2 `Finding`s total (NOT 3): the recurring one
       is NOT duplicated, its `last_seen_scan_run_id` advances to run2 while
       `first_seen_scan_run_id` stays on run1; the new one inserts fresh with
       `first_seen == last_seen == run2`.
    3. The recurring `Finding` is manually suppressed, then a THIRD scan
       re-observes the SAME secret again -> row count is STILL 2, `status`
       stays SUPPRESSED (not reset to OPEN), `last_seen_scan_run_id` advances
       to run3.
    """
    from orchestrator.workers.tasks.process_scan import process_scan_task

    repository_id = asyncio.run(_seed_repository())
    task1_id, run1_id = asyncio.run(_seed_pending_task_for_repository(repository_id))

    recurring_entry = {
        "RuleID": "stripe-access-token",
        "Description": "Stripe Access Token",
        "File": "config.py",
        "StartLine": 4,
        "Secret": "543736274dd00e9ca09b5942773b552873862520",
    }
    docker_client = MagicMock()

    fake_runner1 = FakeContainerRunner()
    fake_runner1.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=2, stdout=json.dumps([recurring_entry]), stderr="", timed_out=False),
    )
    process_scan_task.apply(
        args=(str(task1_id),),
        kwargs={"container_runner": fake_runner1, "docker_client": docker_client},
    ).get()

    rows_after_run1 = asyncio.run(_load_findings_for_repository(repository_id))
    assert len(rows_after_run1) == 1
    assert rows_after_run1[0].first_seen_scan_run_id == run1_id
    assert rows_after_run1[0].last_seen_scan_run_id == run1_id
    assert rows_after_run1[0].status == FindingStatus.OPEN
    recurring_finding_id = rows_after_run1[0].id

    # --- Second scan: re-observes the same secret + a brand-new one ---
    new_entry = {
        "RuleID": "generic-api-key",
        "Description": "Generic API Key",
        "File": "settings.py",
        "StartLine": 9,
        "Secret": "some-other-secret",
    }
    task2_id, run2_id = asyncio.run(_seed_pending_task_for_repository(repository_id))
    fake_runner2 = FakeContainerRunner()
    fake_runner2.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(
            exit_code=2,
            stdout=json.dumps([recurring_entry, new_entry]),
            stderr="",
            timed_out=False,
        ),
    )
    process_scan_task.apply(
        args=(str(task2_id),),
        kwargs={"container_runner": fake_runner2, "docker_client": docker_client},
    ).get()

    rows_after_run2 = asyncio.run(_load_findings_for_repository(repository_id))
    assert len(rows_after_run2) == 2  # deduped: NOT 3
    recurring_row = next(r for r in rows_after_run2 if r.id == recurring_finding_id)
    new_row = next(r for r in rows_after_run2 if r.id != recurring_finding_id)
    assert recurring_row.first_seen_scan_run_id == run1_id  # unchanged
    assert recurring_row.last_seen_scan_run_id == run2_id  # advanced
    assert recurring_row.status == FindingStatus.OPEN
    assert new_row.first_seen_scan_run_id == run2_id
    assert new_row.last_seen_scan_run_id == run2_id

    async def _counts() -> tuple[int, int]:
        engine = create_async_engine(resolve_database_url())
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessionmaker() as session:
                finding_repo = SqlAlchemyFindingRepository(session)
                run1_count = await finding_repo.count_by_last_seen_scan_run(run1_id)
                run2_count = await finding_repo.count_by_last_seen_scan_run(run2_id)
                return run1_count, run2_count
        finally:
            await engine.dispose()

    run1_count, run2_count = asyncio.run(_counts())
    assert run1_count == 0  # the recurring finding moved off run1's count entirely
    assert run2_count == 2  # `GET /scans/{id}` findings_count semantics (D5)

    # --- Suppress the recurring finding, then a third re-scan ---
    asyncio.run(_suppress_finding(recurring_finding_id))

    task3_id, run3_id = asyncio.run(_seed_pending_task_for_repository(repository_id))
    fake_runner3 = FakeContainerRunner()
    fake_runner3.script(
        _CLONE_OK,
        _REV_PARSE_OK,
        RunResult(exit_code=2, stdout=json.dumps([recurring_entry]), stderr="", timed_out=False),
    )
    process_scan_task.apply(
        args=(str(task3_id),),
        kwargs={"container_runner": fake_runner3, "docker_client": docker_client},
    ).get()

    rows_after_run3 = asyncio.run(_load_findings_for_repository(repository_id))
    assert len(rows_after_run3) == 2  # STILL no duplicate row
    recurring_row_after_run3 = next(r for r in rows_after_run3 if r.id == recurring_finding_id)
    assert recurring_row_after_run3.status == FindingStatus.SUPPRESSED  # preserved, not reset
    assert recurring_row_after_run3.first_seen_scan_run_id == run1_id  # still unchanged
    assert recurring_row_after_run3.last_seen_scan_run_id == run3_id  # advanced again
