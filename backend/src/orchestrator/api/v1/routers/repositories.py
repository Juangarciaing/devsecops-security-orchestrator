"""`/api/v1/repositories` — CRUD for tracked `CodeRepository` resources.

All routes require `get_current_user` (member or admin). DELETE additionally
requires `require_role(ADMIN)`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user, require_role
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.code_repository import (
    CodeRepositoryCreate,
    CodeRepositoryRead,
    CodeRepositoryUpdate,
)
from orchestrator.application.use_cases.deactivate_repository import deactivate_repository
from orchestrator.application.use_cases.get_repository import (
    RepositoryNotFoundError,
    get_repository,
)
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
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
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
