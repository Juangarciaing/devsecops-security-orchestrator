"""`/api/v1/findings` endpoints:

- `GET /api/v1/findings` — cross-run filtered, paginated list.
- `GET /api/v1/findings/{id}` — single finding detail.
- `POST /api/v1/findings/{id}/suppress` — `open -> suppressed`.
- `POST /api/v1/findings/{id}/unsuppress` — `suppressed -> open`.

All routes require `get_current_user` (member or admin) — no admin-only
restriction (design: suppress/unsuppress is triage work either role performs,
mirroring `scans.py`'s 2-role convention). Every finding-returning body is
already role-redacted by its use case (D8) before reaching this router.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.use_cases.get_finding import FindingNotFoundError, get_finding
from orchestrator.application.use_cases.list_findings import list_findings
from orchestrator.application.use_cases.suppress_finding import suppress_finding
from orchestrator.application.use_cases.unsuppress_finding import unsuppress_finding
from orchestrator.domain.entities.user import User
from orchestrator.domain.services.finding_transitions import IllegalStatusTransitionError
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus, ScannerType
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)

router = APIRouter(prefix="/api/v1/findings", tags=["findings"])


def _finding_not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Finding not found")


def _illegal_transition(exc: IllegalStatusTransitionError) -> ProblemException:
    return ProblemException(status_code=409, title="Conflict", detail=str(exc))


@router.get("", response_model=list[FindingRead])
async def list_findings_endpoint(
    severity: FindingSeverity | None = None,
    status: FindingStatus | None = None,
    repository_id: uuid.UUID | None = None,
    scanner_type: ScannerType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[FindingRead]:
    finding_port = SqlAlchemyFindingRepository(session)
    return await list_findings(
        finding_port,
        _user.role,
        severity=severity,
        status=status,
        repository_id=repository_id,
        scanner_type=scanner_type,
        limit=limit,
        offset=offset,
    )


@router.get("/{finding_id}", response_model=FindingRead)
async def get_finding_endpoint(
    finding_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FindingRead:
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await get_finding(finding_port, finding_id, _user.role)
    except FindingNotFoundError as exc:
        raise _finding_not_found() from exc


@router.post("/{finding_id}/suppress", response_model=FindingRead)
async def suppress_finding_endpoint(
    finding_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FindingRead:
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await suppress_finding(finding_port, finding_id, _user.role)
    except FindingNotFoundError as exc:
        raise _finding_not_found() from exc
    except IllegalStatusTransitionError as exc:
        raise _illegal_transition(exc) from exc


@router.post("/{finding_id}/unsuppress", response_model=FindingRead)
async def unsuppress_finding_endpoint(
    finding_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FindingRead:
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await unsuppress_finding(finding_port, finding_id, _user.role)
    except FindingNotFoundError as exc:
        raise _finding_not_found() from exc
    except IllegalStatusTransitionError as exc:
        raise _illegal_transition(exc) from exc
