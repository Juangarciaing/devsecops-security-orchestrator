"""`/api/v1/users` — admin-only user provisioning. No public signup path exists."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import require_role
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.user import UserCreate, UserRead
from orchestrator.application.use_cases.create_user import DuplicateEmailError, create_user
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=201)
async def create_user_endpoint(
    payload: UserCreate,
    _admin: User = Depends(require_role(UserRole.ADMIN)),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> UserRead:
    user_port = SqlAlchemyUserRepository(session)
    try:
        created = await create_user(user_port, payload.email, payload.password, payload.role)
    except DuplicateEmailError as exc:
        raise ProblemException(
            status_code=409, title="Conflict", detail="A user with this email already exists"
        ) from exc
    return UserRead.from_entity(created)


@router.get("", response_model=list[UserRead])
async def list_users_endpoint(
    _admin: User = Depends(require_role(UserRole.ADMIN)),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[UserRead]:
    user_port = SqlAlchemyUserRepository(session)
    users = await user_port.list_all()
    return [UserRead.from_entity(user) for user in users]
