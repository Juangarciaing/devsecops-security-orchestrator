"""`get_current_user` / `require_role` — the canonical reusable auth DI guards.

This module carries no endpoint-specific logic (per design D-canonical-guard):
downstream routers/modules import `get_current_user`/`require_role` unmodified.

D6: role rank is `admin=2, member=1` — `require_role(MEMBER)` also passes for
an admin token, since admin is a strict superset of member in this 2-role model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.db.session import get_session
from orchestrator.infrastructure.security.jwt import decode_access_token

_bearer_scheme = HTTPBearer()
# realtime-push PR1 (design D-Auth): `auto_error=False` so a missing header
# falls through to the query-string fallback instead of a framework-level 403.
_optional_bearer_scheme = HTTPBearer(auto_error=False)

_ROLE_RANK: dict[UserRole, int] = {
    UserRole.MEMBER: 1,
    UserRole.ADMIN: 2,
}


def _unauthorized(detail: str) -> ProblemException:
    return ProblemException(status_code=401, title="Unauthorized", detail=detail)


async def _authenticate_token(token: str, session: AsyncSession) -> User:
    """Sole JWT->User verification body. Shared by the bearer and stream paths.

    Raises `ProblemException(401)` on a missing/malformed/expired/tampered
    token, an unknown user id, or an inactive user.
    """
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    repository = SqlAlchemyUserRepository(session)
    user = await repository.get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token")

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> User:
    """Decode the bearer token and load the active `User` it identifies."""
    return await _authenticate_token(credentials.credentials, session)


async def get_stream_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer_scheme),  # noqa: B008
    access_token: str | None = Query(default=None),
) -> User:
    """SSE-route auth (design D-Auth): header-preferred, query-string fallback.

    Deliberately does NOT `Depends(get_db_session)` — that yield-dependency
    stays open for the whole streaming response, pinning one pooled Postgres
    connection per open browser tab for minutes. This opens its own
    short-lived `get_session()` and releases it before the stream begins.
    Resolved at the dependency level (before any `StreamingResponse` body
    starts) so a 401 can still be signalled as an HTTP status.
    """
    token = credentials.credentials if credentials is not None else access_token
    if not token:
        raise _unauthorized("Invalid or expired token")
    async with get_session() as session:
        return await _authenticate_token(token, session)


def require_role(required: UserRole) -> Callable[[User], Awaitable[User]]:
    """Return a dependency raising `ProblemException(403)` if `user`'s role rank is too low."""

    async def _dependency(user: User = Depends(get_current_user)) -> User:  # noqa: B008
        if _ROLE_RANK[user.role] < _ROLE_RANK[required]:
            raise ProblemException(
                status_code=403,
                title="Forbidden",
                detail=f"Requires role '{required.value}' or higher",
            )
        return user

    return _dependency
