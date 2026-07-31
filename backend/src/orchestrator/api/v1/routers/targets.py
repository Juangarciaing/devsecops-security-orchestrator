"""`/api/v1/targets` — CRUD for registered `ScanTarget` resources, plus
`POST /{target_id}/scans` to trigger a DAST scan.

All routes require `get_current_user` (member or admin). DELETE additionally
requires `require_role(ADMIN)` — mirrors `api/v1/routers/repositories.py`.

`POST /{target_id}/scans` fails closed with 403 when `settings.dast_enabled`
is not set (design D9) — checked BEFORE `trigger_scan` is ever called, so no
`ScanRun`/`ScanTask` row is created while DAST is disabled.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user, require_role
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.api.v1.routers.scans import enqueue_committed_scan
from orchestrator.application.dto.scan_run import ScanRunRead
from orchestrator.application.dto.scan_target import (
    ScanTargetCreate,
    ScanTargetRead,
    ScanTargetUpdate,
)
from orchestrator.application.use_cases.deactivate_scan_target import deactivate_scan_target
from orchestrator.application.use_cases.get_scan_target import (
    ScanTargetNotFoundError,
    get_scan_target,
)
from orchestrator.application.use_cases.list_scan_targets import list_scan_targets
from orchestrator.application.use_cases.register_scan_target import (
    DuplicateTargetUrlError,
    register_scan_target,
)
from orchestrator.application.use_cases.trigger_scan import trigger_scan
from orchestrator.application.use_cases.update_scan_target import (
    InvalidScanTargetUpdateError,
    update_scan_target,
)
from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.services.target_url_policy import InvalidTargetUrlError
from orchestrator.domain.value_objects.enums import ScannerType, UserRole
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    SqlAlchemyScanTargetRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Scan target not found")


def _dast_disabled() -> ProblemException:
    return ProblemException(
        status_code=403,
        title="Forbidden",
        detail="DAST scanning is disabled (dast_enabled is unset)",
    )


@router.post("", response_model=ScanTargetRead, status_code=201)
async def register_scan_target_endpoint(
    payload: ScanTargetCreate,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ScanTargetRead:
    target_port = SqlAlchemyScanTargetRepository(session)
    try:
        created = await register_scan_target(target_port, payload.name, payload.target_url)
    except InvalidTargetUrlError as exc:
        raise ProblemException(
            status_code=422, title="Unprocessable Content", detail=str(exc)
        ) from exc
    except DuplicateTargetUrlError as exc:
        raise ProblemException(
            status_code=409, title="Conflict", detail="A target with this URL already exists"
        ) from exc
    return ScanTargetRead.from_entity(created)


@router.get("", response_model=list[ScanTargetRead])
async def list_scan_targets_endpoint(
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[ScanTargetRead]:
    target_port = SqlAlchemyScanTargetRepository(session)
    targets = await list_scan_targets(target_port)
    return [ScanTargetRead.from_entity(target) for target in targets]


@router.get("/{target_id}", response_model=ScanTargetRead)
async def get_scan_target_endpoint(
    target_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ScanTargetRead:
    target_port = SqlAlchemyScanTargetRepository(session)
    try:
        target = await get_scan_target(target_port, target_id)
    except ScanTargetNotFoundError as exc:
        raise _not_found() from exc
    return ScanTargetRead.from_entity(target)


@router.patch("/{target_id}", response_model=ScanTargetRead)
async def update_scan_target_endpoint(
    target_id: uuid.UUID,
    payload: ScanTargetUpdate,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ScanTargetRead:
    target_port = SqlAlchemyScanTargetRepository(session)
    try:
        updated = await update_scan_target(target_port, target_id, payload)
    except InvalidScanTargetUpdateError as exc:
        raise ProblemException(
            status_code=422, title="Unprocessable Content", detail=str(exc)
        ) from exc
    except InvalidTargetUrlError as exc:
        raise ProblemException(
            status_code=422, title="Unprocessable Content", detail=str(exc)
        ) from exc
    except DuplicateTargetUrlError as exc:
        raise ProblemException(
            status_code=409, title="Conflict", detail="A target with this URL already exists"
        ) from exc
    except ScanTargetNotFoundError as exc:
        raise _not_found() from exc
    return ScanTargetRead.from_entity(updated)


@router.delete("/{target_id}", status_code=204)
async def deactivate_scan_target_endpoint(
    target_id: uuid.UUID,
    _admin: User = Depends(require_role(UserRole.ADMIN)),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    target_port = SqlAlchemyScanTargetRepository(session)
    try:
        await deactivate_scan_target(target_port, target_id)
    except ScanTargetNotFoundError as exc:
        raise _not_found() from exc


@router.post("/{target_id}/scans", response_model=ScanRunRead)
async def trigger_target_scan_endpoint(
    target_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    settings = get_settings()
    if not settings.dast_enabled:
        raise _dast_disabled()

    target_port = SqlAlchemyScanTargetRepository(session)
    scan_run_port = SqlAlchemyScanRunRepository(session)
    scan_task_port = SqlAlchemyScanTaskRepository(session)
    # `trigger_scan`'s first positional param is a `CodeRepositoryPort`, but
    # its target-subject branch never dereferences it (`repository_id=None`)
    # — a real DB-backed adapter is passed anyway to keep the call site
    # honest rather than threading a test-only stub into production code.
    repository_port: CodeRepositoryPort = SqlAlchemyCodeRepositoryRepository(session)

    try:
        run, created = await trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository_id=None,
            scanner_type=ScannerType.DAST,
            trigger="manual",
            triggered_by_user_id=user.id,
            scan_target_id=target_id,
            scan_target_port=target_port,
        )
    except ScanTargetNotFoundError as exc:
        raise _not_found() from exc

    if created:
        tasks = await scan_task_port.list_by_scan_run(run.id)
        task = tasks[0]
        await session.commit()  # D4: commit BEFORE enqueue — no uncommitted-read race

        enqueue_committed_scan(str(task.id), ScannerType.DAST)

    status_code = 202 if created else 200
    return JSONResponse(
        status_code=status_code,
        content=ScanRunRead.from_entity(run).model_dump(mode="json"),
    )
