"""`trigger_scan` use case — idempotent scan trigger (D3, D4).

Enqueueing the no-op Celery task is explicitly NOT this use case's job:
per design decision D4 (commit-before-enqueue), the router flushes this use
case's rows, commits, THEN calls `.delay()` itself. This use case only
performs the DB-side idempotency check and `ScanRun`/`ScanTask` creation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus


async def trigger_scan(
    repository_port: CodeRepositoryPort,
    scan_run_port: ScanRunPort,
    scan_task_port: ScanTaskPort,
    repository_id: uuid.UUID,
    commit_sha: str | None = None,
    scanner_type: ScannerType = ScannerType.SECRETS,
    trigger: str = "manual",
) -> tuple[ScanRun, bool]:
    """Trigger a scan for `repository_id`, idempotently.

    Raises `RepositoryNotFoundError` if the repository id does not exist or
    is inactive (404-equivalent, shared with `get_repository`).

    Returns `(existing_run, False)` when an in-flight `ScanTask` already
    matches `(repository_id, resolved_commit_sha, scanner_type)` (D3) — no
    new `ScanRun`/`ScanTask` is created and nothing is re-enqueued.

    Otherwise creates one `ScanRun(status=pending, trigger=trigger)` and one
    `ScanTask(scanner_type, status=pending)`, and returns `(new_run, True)`.
    `trigger` defaults to `"manual"` (module 10 D5: still a plain `str`, no
    `ScanTrigger` enum); the webhook intake (PR3) passes `trigger="webhook"`.
    When `commit_sha` is omitted, both `ScanRun.commit_sha` and
    `ScanRun.ref` default to `repository.default_branch`.

    Never calls `.delay()` — enqueueing after commit is the router's job (D4).
    """
    repository = await repository_port.get_by_id(repository_id)
    if repository is None or not repository.is_active:
        raise RepositoryNotFoundError(repository_id)

    resolved_commit_sha = commit_sha or repository.default_branch

    existing_task = await scan_task_port.find_active_task(
        repository_id, resolved_commit_sha, scanner_type
    )
    if existing_task is not None:
        existing_run = await scan_run_port.get_by_id(existing_task.scan_run_id)
        if existing_run is None:
            raise RuntimeError(
                f"data integrity violation: ScanTask {existing_task.id} references "
                f"missing ScanRun {existing_task.scan_run_id}"
            )
        return existing_run, False

    now = datetime.now(UTC).replace(tzinfo=None)
    scan_run = ScanRun(
        id=uuid.uuid4(),
        repository_id=repository_id,
        status=ScanRunStatus.PENDING,
        trigger=trigger,
        commit_sha=resolved_commit_sha,
        ref=resolved_commit_sha,
        created_at=now,
    )
    created_run = await scan_run_port.create(scan_run)

    scan_task = ScanTask(
        id=uuid.uuid4(),
        scan_run_id=created_run.id,
        scanner_type=scanner_type,
        status=ScanTaskStatus.PENDING,
    )
    await scan_task_port.create(scan_task)

    return created_run, True
