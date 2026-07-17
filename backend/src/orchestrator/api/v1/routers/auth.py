"""`/api/v1/auth` — login, current-user introspection, and the caller's own
API-key issuance/listing/revocation.

Login uses a JSON body (D5), not `OAuth2PasswordRequestForm`: keeps the
request/response shape RFC-7807-consistent and avoids the `python-multipart`
dependency the form flow would require.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import get_current_user
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.application.dto.api_key import ApiKeyCreatedResponse, ApiKeyRead
from orchestrator.application.dto.auth import LoginRequest, TokenResponse
from orchestrator.application.dto.user import UserRead
from orchestrator.application.use_cases.authenticate_user import (
    InvalidCredentialsError,
    authenticate_user,
)
from orchestrator.application.use_cases.issue_api_key import issue_api_key
from orchestrator.domain.entities.user import User
from orchestrator.infrastructure.db.repositories.api_key_repository import (
    ApiKeyNotFoundError,
    SqlAlchemyApiKeyRepository,
)
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.security.jwt import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TokenResponse:
    user_port = SqlAlchemyUserRepository(session)
    try:
        user = await authenticate_user(user_port, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise ProblemException(
            status_code=401, title="Unauthorized", detail="Invalid email or password"
        ) from exc

    return TokenResponse(access_token=create_access_token(user))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:  # noqa: B008
    return UserRead.from_entity(user)


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ApiKeyCreatedResponse:
    api_key_port = SqlAlchemyApiKeyRepository(session)
    created, raw_key = await issue_api_key(api_key_port, user.id)
    return ApiKeyCreatedResponse(api_key=ApiKeyRead.from_entity(created), raw_key=raw_key)


@router.get("/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[ApiKeyRead]:
    api_key_port = SqlAlchemyApiKeyRepository(session)
    keys = await api_key_port.list_for_user(user.id)
    return [ApiKeyRead.from_entity(key) for key in keys]


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ApiKeyRead:
    api_key_port = SqlAlchemyApiKeyRepository(session)
    owned = await api_key_port.list_for_user(user.id)
    if not any(key.id == key_id for key in owned):
        raise ProblemException(status_code=404, title="Not Found", detail="API key not found")

    try:
        revoked = await api_key_port.revoke(key_id)
    except ApiKeyNotFoundError as exc:
        raise ProblemException(
            status_code=404, title="Not Found", detail="API key not found"
        ) from exc
    return ApiKeyRead.from_entity(revoked)
