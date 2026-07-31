"""`trigger_scan` use case — idempotent scan trigger (D3, D4).

Enqueueing the no-op Celery task is explicitly NOT this use case's job:
per design decision D4 (commit-before-enqueue), the router flushes this use
case's rows, commits, THEN calls `.delay()` itself. This use case only
performs the DB-side idempotency check and `ScanRun`/`ScanTask` creation.

dast-scanner PR6: gains an additive `ScanTarget`-subject branch, selected via
`ScanSubject.from_columns(repository_id, scan_target_id)` — exactly one of
the two id params must be set. Every existing repository-subject caller is
unaffected: `repository_id` stays the 4th positional param (now optional in
signature only — every real caller still always passes a concrete value),
and `scan_target_id`/`scan_target_port` are appended last, both defaulted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.get_scan_target import ScanTargetNotFoundError
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_target_port import ScanTargetPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus
from orchestrator.domain.value_objects.scan_subject import ScanSubject, ScanSubjectKind


async def trigger_scan(
    repository_port: CodeRepositoryPort,
    scan_run_port: ScanRunPort,
    scan_task_port: ScanTaskPort,
    repository_id: uuid.UUID | None = None,
    commit_sha: str | None = None,
    scanner_type: ScannerType = ScannerType.SECRETS,
    trigger: str = "manual",
    triggered_by_user_id: uuid.UUID | None = None,
    scan_target_id: uuid.UUID | None = None,
    scan_target_port: ScanTargetPort | None = None,
) -> tuple[ScanRun, bool]:
    """Trigger a scan for exactly one subject — a `CodeRepository` or a
    `ScanTarget` — idempotently.

    Exactly one of `repository_id`/`scan_target_id` MUST be set (enforced by
    `ScanSubject.from_columns`, raising `InvalidScanSubjectError` otherwise).
    Every existing caller passes only `repository_id`, unaffected.

    **Repository-subject branch** (unchanged behavior):

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

    **Scan-target-subject branch** (dast-scanner PR6, design's data flow):

    Requires `scan_target_port` (raises `ValueError` if omitted). Raises
    `ScanTargetNotFoundError` if the target id does not exist or is inactive
    (shared with `get_scan_target`). Idempotency uses
    `find_active_target_task(scan_target_id, scanner_type)` instead of
    `find_active_task` — a target scan has no commit. The created `ScanRun`
    has `repository_id=None`, `commit_sha=None`, `ref=None` — a target has no
    git identity to default a commit/ref from.

    `triggered_by_user_id` (secrets-manager PR6, design D8): the
    authenticated principal for a manually triggered scan, `None` for a
    webhook-triggered one (the router threads its own `_user.id` here; the
    webhook ingest use case never passes it, leaving the default). Recorded
    on `ScanRun` so the worker's credential-access audit trail (D7/D9) can
    attribute a decrypt-and-use to the actual user, not just `"manual"`.

    Never calls `.delay()` — enqueueing after commit is the router's job (D4).
    """
    subject = ScanSubject.from_columns(repository_id, scan_target_id)

    if subject.kind is ScanSubjectKind.SCAN_TARGET:
        if scan_target_port is None:
            raise ValueError("scan_target_port is required when scan_target_id is set")

        target = await scan_target_port.get_by_id(subject.scan_target_id)  # type: ignore[arg-type]
        if target is None or not target.is_active:
            raise ScanTargetNotFoundError(subject.scan_target_id)

        existing_target_task = await scan_task_port.find_active_target_task(
            subject.scan_target_id,  # type: ignore[arg-type]
            scanner_type,
        )
        if existing_target_task is not None:
            existing_target_run = await scan_run_port.get_by_id(existing_target_task.scan_run_id)
            if existing_target_run is None:
                raise RuntimeError(
                    f"data integrity violation: ScanTask {existing_target_task.id} "
                    f"references missing ScanRun {existing_target_task.scan_run_id}"
                )
            return existing_target_run, False

        now = datetime.now(UTC).replace(tzinfo=None)
        target_run = ScanRun(
            id=uuid.uuid4(),
            repository_id=None,
            status=ScanRunStatus.PENDING,
            trigger=trigger,
            commit_sha=None,
            ref=None,
            created_at=now,
            triggered_by_user_id=triggered_by_user_id,
            scan_target_id=subject.scan_target_id,
        )
        created_target_run = await scan_run_port.create(target_run)

        target_task = ScanTask(
            id=uuid.uuid4(),
            scan_run_id=created_target_run.id,
            scanner_type=scanner_type,
            status=ScanTaskStatus.PENDING,
        )
        await scan_task_port.create(target_task)

        return created_target_run, True

    repository = await repository_port.get_by_id(subject.repository_id)  # type: ignore[arg-type]
    if repository is None or not repository.is_active:
        raise RepositoryNotFoundError(subject.repository_id)

    resolved_commit_sha = commit_sha or repository.default_branch

    existing_task = await scan_task_port.find_active_task(
        subject.repository_id,  # type: ignore[arg-type]
        resolved_commit_sha,
        scanner_type,
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
        repository_id=subject.repository_id,
        status=ScanRunStatus.PENDING,
        trigger=trigger,
        commit_sha=resolved_commit_sha,
        ref=resolved_commit_sha,
        created_at=now,
        triggered_by_user_id=triggered_by_user_id,
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
