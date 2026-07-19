"""Scan orchestration endpoints:

- `POST /api/v1/repositories/{repository_id}/scans` — trigger (idempotent).
- `GET /api/v1/scans` — paginated list.
- `GET /api/v1/scans/{scan_run_id}` — status + findings count.

All routes require `get_current_user` (member or admin) — no admin-only
endpoint here (unlike `repositories.py`'s DELETE).

Commit-before-enqueue (design D4): the trigger endpoint explicitly commits
the session BEFORE calling `process_scan_task.delay(...)`, so the worker
never dereferences an uncommitted `scan_task_id`. `get_db_session`'s trailing
commit (see `infrastructure/db/session.py`) is then a no-op for that request.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.dto.scan_run import ScanRunRead
from orchestrator.application.dto.scan_trigger import ScanRunDetailRead, ScanTriggerRequest
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.get_scan_run_detail import (
    ScanRunNotFoundError,
    get_scan_run_detail,
)
from orchestrator.application.use_cases.list_scan_findings import (
    ScanRunNotFoundError as ListScanFindingsNotFoundError,
)
from orchestrator.application.use_cases.list_scan_findings import list_scan_findings
from orchestrator.application.use_cases.list_scan_runs import list_scan_runs
from orchestrator.application.use_cases.trigger_scan import trigger_scan
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import ScannerType
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

router = APIRouter(prefix="/api/v1", tags=["scans"])


def _repository_not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Repository not found")


def _scan_not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Scan not found")


@router.post("/repositories/{repository_id}/scans", response_model=ScanRunRead)
async def trigger_scan_endpoint(
    repository_id: uuid.UUID,
    payload: ScanTriggerRequest | None = None,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    scan_run_port = SqlAlchemyScanRunRepository(session)
    scan_task_port = SqlAlchemyScanTaskRepository(session)

    commit_sha = payload.commit_sha if payload is not None else None
    scanner_type = (
        payload.scanner_type if payload is not None and payload.scanner_type is not None else None
    ) or ScannerType.SECRETS

    try:
        run, created = await trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository_id,
            commit_sha,
            scanner_type,
            trigger="manual",
        )
    except RepositoryNotFoundError as exc:
        raise _repository_not_found() from exc

    if created:
        tasks = await scan_task_port.list_by_scan_run(run.id)
        task = tasks[0]
        await session.commit()  # D4: commit BEFORE enqueue — no uncommitted-read race

        # Imported lazily (not at module top level): `celery_app.py` resolves
        # `Settings()` eagerly at import time (standard Celery `-A module`
        # requirement, PR2 D1). Importing it at `scans.py`'s module level
        # would force every test that imports `create_app()` — including
        # ones with no interest in Celery — to pre-populate Settings' env
        # vars before test collection even runs, exactly the constraint
        # `tests/unit/workers/test_celery_app.py` and
        # `tests/integration/test_process_scan_task.py` already work around.
        from orchestrator.workers.tasks.process_scan import process_scan_task

        process_scan_task.delay(str(task.id))

    status_code = 202 if created else 200
    return JSONResponse(
        status_code=status_code,
        content=ScanRunRead.from_entity(run).model_dump(mode="json"),
    )


@router.get("/scans", response_model=list[ScanRunRead])
async def list_scans_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[ScanRunRead]:
    scan_run_port = SqlAlchemyScanRunRepository(session)
    runs = await list_scan_runs(scan_run_port, limit, offset)
    return [ScanRunRead.from_entity(run) for run in runs]


@router.get("/scans/{scan_run_id}", response_model=ScanRunDetailRead)
async def get_scan_endpoint(
    scan_run_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ScanRunDetailRead:
    scan_run_port = SqlAlchemyScanRunRepository(session)
    scan_task_port = SqlAlchemyScanTaskRepository(session)
    finding_repository = SqlAlchemyFindingRepository(session)

    try:
        run, task, findings_count = await get_scan_run_detail(
            scan_run_port, scan_task_port, finding_repository, scan_run_id
        )
    except ScanRunNotFoundError as exc:
        raise _scan_not_found() from exc

    return ScanRunDetailRead.from_run_task_and_count(run, task, findings_count)


@router.get("/scans/{scan_run_id}/findings", response_model=list[FindingRead])
async def list_scan_findings_endpoint(
    scan_run_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[FindingRead]:
    scan_run_port = SqlAlchemyScanRunRepository(session)
    finding_port = SqlAlchemyFindingRepository(session)

    try:
        return await list_scan_findings(
            scan_run_port, finding_port, scan_run_id, _user.role, limit, offset
        )
    except ListScanFindingsNotFoundError as exc:
        raise _scan_not_found() from exc
