"""`/api/v1/repositories` — CRUD for tracked `CodeRepository` resources.

All routes require `get_current_user` (member or admin). DELETE additionally
requires `require_role(ADMIN)`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user, require_role
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.code_repository import (
    CodeRepositoryCreate,
    CodeRepositoryRead,
    CodeRepositoryUpdate,
)
from orchestrator.application.dto.diff import RepositoryDiffRead
from orchestrator.application.dto.policy import RepositoryPolicyRead
from orchestrator.application.dto.trends import RepositoryTrendsRead
from orchestrator.application.use_cases.deactivate_repository import deactivate_repository
from orchestrator.application.use_cases.evaluate_repository_policy import (
    evaluate_repository_policy,
)
from orchestrator.application.use_cases.get_repository import (
    RepositoryNotFoundError,
    get_repository,
)
from orchestrator.application.use_cases.get_repository_diff import get_repository_diff
from orchestrator.application.use_cases.get_repository_trends import get_repository_trends
from orchestrator.application.use_cases.list_repositories import list_repositories
from orchestrator.application.use_cases.register_repository import (
    DuplicateRepositoryIdentityError,
    register_repository,
)
from orchestrator.application.use_cases.update_repository import (
    InvalidRepositoryUpdateError,
    update_repository,
)
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import ScannerType, UserRole
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


def _not_found() -> ProblemException:
    return ProblemException(status_code=404, title="Not Found", detail="Repository not found")


@router.post("", response_model=CodeRepositoryRead, status_code=201)
async def register_repository_endpoint(
    payload: CodeRepositoryCreate,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CodeRepositoryRead:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    try:
        created = await register_repository(
            repository_port,
            payload.provider,
            payload.owner,
            payload.name,
            payload.clone_url,
            payload.default_branch,
            payload.credential_ref,
        )
    except DuplicateRepositoryIdentityError as exc:
        raise ProblemException(
            status_code=409,
            title="Conflict",
            detail="A repository with this provider/owner/name already exists",
        ) from exc
    return CodeRepositoryRead.from_entity(created)


@router.get("", response_model=list[CodeRepositoryRead])
async def list_repositories_endpoint(
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[CodeRepositoryRead]:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    repositories = await list_repositories(repository_port)
    return [CodeRepositoryRead.from_entity(repository) for repository in repositories]


@router.get("/{repository_id}", response_model=CodeRepositoryRead)
async def get_repository_endpoint(
    repository_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CodeRepositoryRead:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    try:
        repository = await get_repository(repository_port, repository_id)
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc
    return CodeRepositoryRead.from_entity(repository)


@router.get("/{repository_id}/trends", response_model=RepositoryTrendsRead)
async def get_repository_trends_endpoint(
    repository_id: uuid.UUID,
    scanner_type: ScannerType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RepositoryTrendsRead:
    """Exact introduced-per-run (by severity) + current-open snapshot for
    `repository_id`. No per-role redaction (design D3): aggregate severity
    counts never carry `Finding.REDACTION_SENSITIVE_FIELDS`, so member and
    admin callers receive identical bodies.
    """
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await get_repository_trends(
            repository_port,
            finding_port,
            repository_id,
            scanner_type=scanner_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc


@router.get("/{repository_id}/diff", response_model=RepositoryDiffRead)
async def get_repository_diff_endpoint(
    repository_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RepositoryDiffRead:
    """Exact ADDED/RESOLVED/CARRIED finding partition between `repository_id`'s
    latest completed `ScanRun` and the run immediately before it — always
    latest-vs-immediately-previous, no baseline-override parameter (design
    D1: a non-adjacent baseline would reintroduce the gap-loss this feature
    exists to avoid). Unlike `/trends`, every returned finding is redacted
    per the caller's `role` (design's per-finding redaction requirement).
    """
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    scan_run_port = SqlAlchemyScanRunRepository(session)
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await get_repository_diff(
            repository_port, scan_run_port, finding_port, repository_id, user.role
        )
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc


@router.get("/{repository_id}/policy-check", response_model=RepositoryPolicyRead)
async def get_repository_policy_check_endpoint(
    repository_id: uuid.UUID,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RepositoryPolicyRead:
    """Pure pass/fail quality-gate verdict for `repository_id` — a fixed
    global `{CRITICAL, HIGH}` blocking-severity threshold over
    `FindingPort.open_counts_by_severity` (Module 12a). No per-role
    redaction (design D3): the body carries only counts, never finding
    bodies, so member and admin callers receive byte-identical responses.
    """
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    finding_port = SqlAlchemyFindingRepository(session)
    try:
        return await evaluate_repository_policy(repository_port, finding_port, repository_id)
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc


@router.patch("/{repository_id}", response_model=CodeRepositoryRead)
async def update_repository_endpoint(
    repository_id: uuid.UUID,
    payload: CodeRepositoryUpdate,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CodeRepositoryRead:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    try:
        updated = await update_repository(repository_port, repository_id, payload)
    except InvalidRepositoryUpdateError as exc:
        raise ProblemException(
            status_code=422, title="Unprocessable Content", detail=str(exc)
        ) from exc
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc
    return CodeRepositoryRead.from_entity(updated)


@router.delete("/{repository_id}", status_code=204)
async def deactivate_repository_endpoint(
    repository_id: uuid.UUID,
    _admin: User = Depends(require_role(UserRole.ADMIN)),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    try:
        await deactivate_repository(repository_port, repository_id)
    except RepositoryNotFoundError as exc:
        raise _not_found() from exc
