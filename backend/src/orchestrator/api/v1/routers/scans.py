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

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user, get_stream_user
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.dependencies.realtime import get_relay, require_realtime_enabled
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
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus
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
from orchestrator.infrastructure.db.session import get_session
from orchestrator.infrastructure.observability.metrics import record_scan_accepted
from orchestrator.infrastructure.realtime.events import ScanStatusEvent

router = APIRouter(prefix="/api/v1", tags=["scans"])

# design D-Transport: `X-Accel-Buffering: no` directly mitigates nginx
# buffering an SSE response; no `sse-starlette` dependency (see design).
_HEARTBEAT_SECONDS = 15
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_TERMINAL_SCAN_STATUSES = {ScanRunStatus.COMPLETED, ScanRunStatus.FAILED, ScanRunStatus.CANCELLED}


def _repository_not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Repository not found")


def _scan_not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Scan not found")


def enqueue_committed_scan(task_id: str, scanner_type: ScannerType) -> None:
    """Enqueue a committed task, then record acceptance only if enqueue succeeds."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    process_scan_task.delay(task_id)
    record_scan_accepted(scanner_type)


@router.post("/repositories/{repository_id}/scans", response_model=ScanRunRead)
async def trigger_scan_endpoint(
    repository_id: uuid.UUID,
    payload: ScanTriggerRequest | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
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
            # secrets-manager PR6/D8: the authenticated principal for THIS
            # manual trigger — the worker's credential-access audit trail
            # attributes a decrypt-and-use to this user, not just "manual".
            triggered_by_user_id=user.id,
        )
    except RepositoryNotFoundError as exc:
        raise _repository_not_found() from exc

    if created:
        tasks = await scan_task_port.list_by_scan_run(run.id)
        task = tasks[0]
        await session.commit()  # D4: commit BEFORE enqueue — no uncommitted-read race

        enqueue_committed_scan(str(task.id), scanner_type)

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


def _frame(event: str, data: str) -> str:
    """Pure SSE framing — byte-exact `event: X\\ndata: Y\\n\\n`, no server needed."""
    return f"event: {event}\ndata: {data}\n\n"


def _is_terminal(payload: str) -> bool:
    try:
        event = ScanStatusEvent.from_json(payload)
    except (ValueError, KeyError):
        return False
    return event.status in _TERMINAL_SCAN_STATUSES


async def _get_scan_run(session: AsyncSession, scan_run_id: uuid.UUID) -> ScanRun | None:
    scan_run_port = SqlAlchemyScanRunRepository(session)
    return await scan_run_port.get_by_id(scan_run_id)


@router.get(
    "/scans/{scan_run_id}/events",
    dependencies=[Depends(require_realtime_enabled)],  # resolved before auth/DB (design D-Gate)
)
async def stream_scan_events(
    scan_run_id: uuid.UUID,
    request: Request,
    _user: User = Depends(get_stream_user),  # noqa: B008
) -> StreamingResponse:
    """SSE stream of `scan.status` events for `scan_run_id` (design D-Transport).

    The existence check uses its own short-lived session, closed BEFORE the
    stream begins — mirrors `get_stream_user`'s reasoning: a `StreamingResponse`
    must never pin a pooled DB connection for the connection's lifetime.

    A scan already in a terminal status when this connects gets exactly ONE
    event reflecting its current status, then closes immediately — it MUST
    NOT subscribe to the relay, since the transition already happened before
    this connection existed and no future publish for it will ever arrive
    (a subscribed connection would otherwise heartbeat forever, waiting on
    an event that can never come).
    """
    async with get_session() as session:
        scan_run = await _get_scan_run(session, scan_run_id)
    if scan_run is None:
        raise _scan_not_found()

    if scan_run.status in _TERMINAL_SCAN_STATUSES:
        at = (scan_run.completed_at or scan_run.created_at).isoformat()
        terminal_event = ScanStatusEvent(scan_run_id=scan_run_id, status=scan_run.status, at=at)

        async def _terminal_only() -> AsyncIterator[str]:
            yield _frame("scan.status", terminal_event.to_json())

        return StreamingResponse(
            _terminal_only(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    relay = get_relay(request)

    async def _events() -> AsyncIterator[str]:
        async with relay.subscribe(str(scan_run_id)) as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _frame("scan.status", payload)
                if _is_terminal(payload):
                    return

    return StreamingResponse(_events(), media_type="text/event-stream", headers=_SSE_HEADERS)
