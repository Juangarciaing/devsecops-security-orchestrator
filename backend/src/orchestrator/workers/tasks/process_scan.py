"""`process_scan_task` — the no-op Celery scan task (D2, D5).

Drives the `ScanRun`/`ScanTask` state machine (`pending -> running ->
completed`, or `-> failed` once retries are exhausted) and writes exactly one
deterministic placeholder `Finding` on success. Every DB access happens
through `workers.db.run_async` (D2): a fresh `NullPool` engine/session per
call, disposed in `finally`, sidestepping the asyncpg/event-loop cross-binding
issue a shared, cached engine would hit across separate `asyncio.run` calls.

Retry/backoff is manual (D5): on `TransientScanError`, `self.retry()` raises
`Retry` to replay the task (in eager/`Task.apply()` mode this happens
immediately and synchronously via Celery's own retry recursion, ignoring
`countdown`) until `max_retries` is exhausted, at which point it re-raises
(`MaxRetriesExceededError`, or the original `exc` since one was supplied).
This task catches both to make the terminal `failed` transition explicit and
guaranteed rather than letting either propagate uncaught.

`simulate_failure`/`fail_attempts` are test-only hooks for exercising the
retry path without a real flaky scanner (production callers never pass
them): `simulate_failure=True, fail_attempts=None` fails on every attempt
(exercises full backoff -> terminal `failed`); `fail_attempts=N` (N <
`max_retries`) fails only while `self.request.retries < N`, then succeeds
(exercises backoff -> eventual `completed`).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from celery import Task
from celery.exceptions import MaxRetriesExceededError
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingSeverity, ScanRunStatus, ScanTaskStatus
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    ScanTaskNotFoundError,
    SqlAlchemyScanTaskRepository,
)
from orchestrator.workers.backoff import backoff_jitter
from orchestrator.workers.celery_app import celery_app
from orchestrator.workers.db import run_async

logger = get_task_logger(__name__)

MAX_RETRIES = 5


class TransientScanError(RuntimeError):
    """Raised when the no-op scan simulates a transient, retryable failure (D5)."""


def _placeholder_fingerprint(scan_task_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{scan_task_id}:placeholder".encode()).hexdigest()


async def _run_scan(session: AsyncSession, scan_task_id: uuid.UUID, should_fail: bool) -> None:
    """Drive one attempt: `pending -> running` (idempotent), then either raise
    `TransientScanError` or write the placeholder `Finding` and complete.
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    finding_repo = SqlAlchemyFindingRepository(session)

    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)

    now = datetime.now(UTC).replace(tzinfo=None)
    if task.status == ScanTaskStatus.PENDING:
        await scan_task_repo.update_status(scan_task_id, ScanTaskStatus.RUNNING, started_at=now)
        await scan_run_repo.update_status(task.scan_run_id, ScanRunStatus.RUNNING, started_at=now)
        await session.commit()

    if should_fail:
        raise TransientScanError(f"simulated transient failure for scan_task {scan_task_id}")

    finding = Finding(
        id=uuid.uuid4(),
        scan_task_id=scan_task_id,
        severity=FindingSeverity.INFO,
        rule_id="placeholder",
        title="Placeholder finding (no-op scan)",
        fingerprint=_placeholder_fingerprint(scan_task_id),
        created_at=now,
        updated_at=now,
    )
    await finding_repo.create(finding)

    completed_at = datetime.now(UTC).replace(tzinfo=None)
    await scan_task_repo.update_status(
        scan_task_id, ScanTaskStatus.COMPLETED, completed_at=completed_at
    )
    await scan_run_repo.update_status(
        task.scan_run_id, ScanRunStatus.COMPLETED, completed_at=completed_at
    )
    await session.commit()


async def _mark_failed(session: AsyncSession, scan_task_id: uuid.UUID, error_message: str) -> None:
    """Terminal `failed` transition for both `ScanTask` and its `ScanRun` (D5)."""
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)

    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)

    now = datetime.now(UTC).replace(tzinfo=None)
    await scan_task_repo.update_status(
        scan_task_id, ScanTaskStatus.FAILED, completed_at=now, error_message=error_message
    )
    await scan_run_repo.update_status(task.scan_run_id, ScanRunStatus.FAILED, completed_at=now)
    await session.commit()


@celery_app.task(bind=True, max_retries=MAX_RETRIES)  # type: ignore[untyped-decorator]
def process_scan_task(
    self: Task,
    scan_task_id: str,
    simulate_failure: bool = False,
    fail_attempts: int | None = None,
) -> None:
    """Run the no-op scan for `scan_task_id` (a stringified UUID).

    `simulate_failure`/`fail_attempts` are test-only hooks (see module
    docstring) — production callers never pass them.
    """
    task_id = uuid.UUID(scan_task_id)
    should_fail = simulate_failure and (
        fail_attempts is None or self.request.retries < fail_attempts
    )

    try:
        run_async(lambda session: _run_scan(session, task_id, should_fail))
    except TransientScanError as exc:
        error_message = str(exc)
        try:
            self.retry(exc=exc, countdown=backoff_jitter(self.request.retries))
        except (MaxRetriesExceededError, TransientScanError):
            # `self.retry(exc=exc, ...)`, once `max_retries` is exhausted,
            # re-raises the ORIGINAL `exc` (here, `TransientScanError`)
            # rather than `MaxRetriesExceededError` when `exc` was given —
            # catch both to make the terminal `failed` transition explicit
            # and guaranteed either way (D5).
            logger.warning("scan_task %s exhausted retries: %s", task_id, error_message)
            run_async(lambda session: _mark_failed(session, task_id, error_message))
