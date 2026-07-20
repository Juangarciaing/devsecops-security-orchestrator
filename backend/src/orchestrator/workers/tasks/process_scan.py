"""`process_scan_task` — the real Module 6/7 scan flow (D1-D6).

## Flow
    run_async: load task -> run -> repository; pending -> running          [DB]
    sync:      get_adapter(task.scanner_type, runner, settings)            [registry, D2/D6]
               GitCheckout(...).checkout(clone_url, ref) -> Workspace      [init container]
               adapter.scan(workspace.volume_name)                        [scanner container]
               adapter.parse(RunResult, scan_task_id) -> list[Finding]
               # Workspace.__exit__ force-removes the volume (finally)
    run_async: persist resolved commit_sha + bulk_upsert_findings(...)     [DB, dedup on
               (repository_id, fingerprint); task + run -> completed        Module 7 D4/D6]

Container work (checkout + scan) is sync/blocking (the `docker` SDK itself
is sync, Module 6 D3) and runs OUTSIDE any async DB session/event loop —
`run_async` is called twice, before and after, never around it.

## Failure classification (D5)
- `CheckoutFailedError` / `GitleaksFailedError` / `PipAuditFailedError` /
  `SastFailedError` (bad ref, private repo, a genuine non-{0,2} Gitleaks exit
  code, a malformed/empty/timed-out pip-audit report, a missing-JSON/malformed/
  timed-out sast-scanner report, or a wall-clock timeout) are DETERMINISTIC —
  a retry cannot fix them. These go straight to `failed`, bypassing Module 5's
  retry/backoff machinery entirely (one attempt only). (Module 11 D7:
  `PipAuditFailedError` added alongside the two pre-existing Gitleaks/Checkout
  classifications; Module 11 D5 (AST-SAST, PR2): `SastFailedError` added the
  same way — additive, backward-compatible.)
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
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus
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
from orchestrator.infrastructure.scanners.ast_sast_adapter import SastFailedError
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError
from orchestrator.infrastructure.scanners.pip_audit_adapter import PipAuditFailedError
from orchestrator.infrastructure.scanners.registry import get_adapter
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
) -> tuple[str, str, uuid.UUID, uuid.UUID, ScannerType]:
    """Load the repo's `clone_url` + the run's `ref`; transition `pending -> running`.

    Returns `(clone_url, ref, scan_run_id, repository_id, scanner_type)`.
    Idempotent on the `pending -> running` transition, matching Module 5's
    original convention.

    `repository_id`/`scanner_type` are returned so `_checkout_and_scan`
    (registry-routed, Module 7 D2/D6) and `_complete_scan`
    (`bulk_upsert_findings`, Module 7 D4/D6) don't need to re-load `task`/
    `repository` themselves.
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

    return repository.clone_url, run.ref, task.scan_run_id, repository.id, task.scanner_type


def _checkout_and_scan(
    clone_url: str,
    ref: str,
    scan_task_id: uuid.UUID,
    scanner_type: ScannerType,
    runner: ContainerRunnerPort,
    docker_client: DockerClient,
    settings: Settings,
) -> tuple[str, list[Finding]]:
    """Sync/blocking: resolve the adapter, checkout, scan, parse. Runs OUTSIDE
    any async DB session/event loop (Module 6 D3).

    The adapter is resolved via `registry.get_adapter(scanner_type, ...)`
    (Module 7 D2/D6) instead of a hardcoded `GitleaksAdapter(...)` — this is
    what actually makes `ScanTask.scanner_type` meaningful. Raises
    `UnregisteredScannerError` (via `get_adapter`) for any `scanner_type`
    with no registration; `CheckoutFailedError` (deterministic, from
    `GitCheckout`), `GitleaksFailedError` (deterministic, from
    `GitleaksAdapter.parse()`), `PipAuditFailedError` (deterministic,
    from `PipAuditAdapter.scan()`/`.parse()`, Module 11 D7), or
    `SastFailedError` (deterministic, from `AstSastAdapter.parse()`,
    Module 11 D5, PR2) unchanged — callers classify those as non-retryable
    (D5). Any OTHER exception (including `UnregisteredScannerError`) is left
    to propagate to the caller, which wraps it as `TransientScanError`.
    """
    adapter = get_adapter(scanner_type, runner, settings)
    with GitCheckout(runner, docker_client, settings).checkout(clone_url, ref) as workspace:
        result = adapter.scan(workspace.volume_name)
    return workspace.head_sha, adapter.parse(result, scan_task_id)


async def _complete_scan(
    session: AsyncSession,
    scan_task_id: uuid.UUID,
    scan_run_id: uuid.UUID,
    repository_id: uuid.UUID,
    head_sha: str,
    findings: list[Finding],
) -> None:
    """Persist the resolved HEAD SHA + `Finding`s; `task`/`run` -> `completed`.

    Zero `findings` (a clean repo) is a valid, successful outcome (D4/spec) —
    NOT treated as failure (`bulk_upsert_findings` no-ops on an empty list).

    Persistence is ONE `bulk_upsert_findings(repository_id, scan_run_id,
    findings)` call (Module 7 D4/D6) — REPLACES the former per-finding
    `create()` loop. This is what actually gives cross-run dedup on re-scans:
    a `Finding` whose `(repository_id, fingerprint)` was already seen has its
    `last_seen_scan_run_id` advanced (and `status` left untouched — suppressed
    stays suppressed) instead of inserting a duplicate row; a brand-new
    fingerprint inserts with `first_seen_scan_run_id == last_seen_scan_run_id
    == scan_run_id`.
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    finding_repo = SqlAlchemyFindingRepository(session)

    await scan_run_repo.update_commit_sha(scan_run_id, head_sha)
    await finding_repo.bulk_upsert_findings(repository_id, scan_run_id, findings)

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
            clone_url, ref, scan_run_id, repository_id, scanner_type = run_async(
                lambda session: _load_and_start(session, task_id)
            )
            try:
                head_sha, findings = _checkout_and_scan(
                    clone_url, ref, task_id, scanner_type, runner, client, settings
                )
            except (CheckoutFailedError, GitleaksFailedError, PipAuditFailedError, SastFailedError):
                raise
            except Exception as exc:
                # Docker-daemon/network blip, not a deterministic checkout/scan
                # failure (D5) — hand off to Module 5's existing retry/backoff.
                raise TransientScanError(str(exc)) from exc

            run_async(
                lambda session: _complete_scan(
                    session, task_id, scan_run_id, repository_id, head_sha, findings
                )
            )
        finally:
            if docker_client is None:
                client.close()
    except (CheckoutFailedError, GitleaksFailedError, PipAuditFailedError, SastFailedError) as exc:
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
