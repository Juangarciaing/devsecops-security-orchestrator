"""`process_scan_task` — the real Module 6 scan flow (D1-D5).

## Flow
    run_async: load task -> run -> repository; pending -> running          [DB]
    sync:      GitCheckout(...).checkout(clone_url, ref) -> Workspace      [init container]
               GitleaksAdapter(...).scan(workspace.volume_name)            [scanner container]
               GitleaksAdapter(...).parse(RunResult) -> list[Finding]
               # Workspace.__exit__ force-removes the volume (finally)
    run_async: persist resolved commit_sha + Finding(s);
               task + run -> completed                                    [DB]

Container work (checkout + scan) is sync/blocking (the `docker` SDK itself
is sync, Module 6 D3) and runs OUTSIDE any async DB session/event loop —
`run_async` is called twice, before and after, never around it.

## Failure classification (D5)
- `CheckoutFailedError` / `GitleaksFailedError` (bad ref, private repo, a
  genuine non-{0,2} Gitleaks exit code, or a wall-clock timeout) are
  DETERMINISTIC — a retry cannot fix them. These go straight to `failed`,
  bypassing Module 5's retry/backoff machinery entirely (one attempt only).
- Any OTHER exception raised while checking out/scanning (Docker-daemon
  blips, network errors, ...) is wrapped as `TransientScanError` and handed
  to the EXACT SAME retry/backoff loop Module 5 already built — this module
  only changes WHAT the task body does when it runs, never the surrounding
  state-machine/retry plumbing.

`container_runner`/`docker_client` are test-only injection kwargs (mirrors
Module 5's `simulate_failure`/`fail_attempts` precedent): production callers
never pass them (defaults construct a real `DockerContainerRunner`/
`docker.from_env()`); tests inject a `FakeContainerRunner` + a `MagicMock`
docker client instead (see `tests/integration/test_process_scan_task.py`,
which mirrors the `FakeContainerRunner`/`MagicMock` double already
established by `tests/unit/infrastructure/test_git_checkout.py`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import docker
from celery import Task
from celery.exceptions import MaxRetriesExceededError
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import ScanRunStatus, ScanTaskStatus
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    CodeRepositoryNotFoundError,
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
from orchestrator.infrastructure.scanners.gitleaks_adapter import (
    GitleaksAdapter,
    GitleaksFailedError,
)
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError, GitCheckout
from orchestrator.workers.backoff import backoff_jitter
from orchestrator.workers.celery_app import celery_app
from orchestrator.workers.db import run_async

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.infrastructure.config.settings import Settings

logger = get_task_logger(__name__)

MAX_RETRIES = 5


class TransientScanError(RuntimeError):
    """A retryable, non-deterministic failure (Docker-daemon/network blip, D5).

    NEVER raised for a deterministic outcome (`CheckoutFailedError`,
    `GitleaksFailedError`) — those bypass retry entirely and go straight to
    `failed` (D5).
    """


async def _load_and_start(
    session: AsyncSession, scan_task_id: uuid.UUID
) -> tuple[str, str, uuid.UUID]:
    """Load the repo's `clone_url` + the run's `ref`; transition `pending -> running`.

    Returns `(clone_url, ref, scan_run_id)`. Idempotent on the `pending ->
    running` transition, matching Module 5's original convention.
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    code_repository_repo = SqlAlchemyCodeRepositoryRepository(session)

    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)
    run = await scan_run_repo.get_by_id(task.scan_run_id)
    if run is None:
        raise ScanRunNotFoundError(task.scan_run_id)
    repository = await code_repository_repo.get_by_id(run.repository_id)
    if repository is None:
        raise CodeRepositoryNotFoundError(run.repository_id)

    now = datetime.now(UTC).replace(tzinfo=None)
    if task.status == ScanTaskStatus.PENDING:
        await scan_task_repo.update_status(scan_task_id, ScanTaskStatus.RUNNING, started_at=now)
        await scan_run_repo.update_status(task.scan_run_id, ScanRunStatus.RUNNING, started_at=now)
        await session.commit()

    return repository.clone_url, run.ref, task.scan_run_id


def _checkout_and_scan(
    clone_url: str,
    ref: str,
    scan_task_id: uuid.UUID,
    runner: ContainerRunnerPort,
    docker_client: DockerClient,
    settings: Settings,
) -> tuple[str, list[Finding]]:
    """Sync/blocking: checkout + run Gitleaks + parse. Runs OUTSIDE any async
    DB session/event loop (Module 6 D3).

    Raises `CheckoutFailedError` (deterministic, from `GitCheckout`) or
    `GitleaksFailedError` (deterministic, from `GitleaksAdapter.parse()`)
    unchanged — callers classify those as non-retryable (D5). Any OTHER
    exception is left to propagate to the caller, which wraps it as
    `TransientScanError`.

    Note: this is a minimal Module 7 PR1 compatibility fix (calling
    `GitleaksAdapter.parse()` as a method instead of the deleted
    module-level `parse()`) — NOT the full registry-routed re-wire (that is
    Module 7 PR4, D6).
    """
    adapter = GitleaksAdapter(runner, settings)
    with GitCheckout(runner, docker_client, settings).checkout(clone_url, ref) as workspace:
        result = adapter.scan(workspace.volume_name)
    return workspace.head_sha, adapter.parse(result, scan_task_id)


async def _complete_scan(
    session: AsyncSession,
    scan_task_id: uuid.UUID,
    scan_run_id: uuid.UUID,
    head_sha: str,
    findings: list[Finding],
) -> None:
    """Persist the resolved HEAD SHA + `Finding`s; `task`/`run` -> `completed`.

    Zero `findings` (a clean repo) is a valid, successful outcome (D4/spec) —
    NOT treated as failure.
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    finding_repo = SqlAlchemyFindingRepository(session)

    await scan_run_repo.update_commit_sha(scan_run_id, head_sha)
    for finding in findings:
        await finding_repo.create(finding)

    completed_at = datetime.now(UTC).replace(tzinfo=None)
    await scan_task_repo.update_status(
        scan_task_id, ScanTaskStatus.COMPLETED, completed_at=completed_at
    )
    await scan_run_repo.update_status(
        scan_run_id, ScanRunStatus.COMPLETED, completed_at=completed_at
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
    container_runner: ContainerRunnerPort | None = None,
    docker_client: DockerClient | None = None,
) -> None:
    """Run the real scan for `scan_task_id` (a stringified UUID).

    `container_runner`/`docker_client` are test-only injection hooks (see
    module docstring) — production callers never pass them.
    """
    task_id = uuid.UUID(scan_task_id)
    settings = get_settings()
    client = docker_client if docker_client is not None else docker.from_env()
    runner = container_runner if container_runner is not None else DockerContainerRunner(client)

    try:
        try:
            clone_url, ref, scan_run_id = run_async(
                lambda session: _load_and_start(session, task_id)
            )
            try:
                head_sha, findings = _checkout_and_scan(
                    clone_url, ref, task_id, runner, client, settings
                )
            except (CheckoutFailedError, GitleaksFailedError):
                raise
            except Exception as exc:
                # Docker-daemon/network blip, not a deterministic checkout/scan
                # failure (D5) — hand off to Module 5's existing retry/backoff.
                raise TransientScanError(str(exc)) from exc

            run_async(
                lambda session: _complete_scan(session, task_id, scan_run_id, head_sha, findings)
            )
        finally:
            if docker_client is None:
                client.close()
    except (CheckoutFailedError, GitleaksFailedError) as exc:
        error_message = str(exc)
        logger.warning("scan_task %s failed deterministically: %s", task_id, error_message)
        run_async(lambda session: _mark_failed(session, task_id, error_message))
    except TransientScanError as exc:
        error_message = str(exc)
        try:
            self.retry(exc=exc, countdown=backoff_jitter(self.request.retries))
        except (MaxRetriesExceededError, TransientScanError):
            # `self.retry(exc=exc, ...)`, once `max_retries` is exhausted,
            # re-raises the ORIGINAL `exc` (here, `TransientScanError`)
            # rather than `MaxRetriesExceededError` when `exc` was given —
            # catch both to make the terminal `failed` transition explicit
            # and guaranteed either way (D5, Module 5 precedent).
            logger.warning("scan_task %s exhausted retries: %s", task_id, error_message)
            run_async(lambda session: _mark_failed(session, task_id, error_message))
