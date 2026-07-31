"""`get_current_user` / `require_role` — the canonical reusable DI guards.

No live Postgres/session is needed: `SqlAlchemyUserRepository` is stubbed at
the `auth` module boundary so these tests exercise only the guard logic
(token decoding, active-user check, role-rank comparison per D6).

No `pytest-asyncio` plugin in this project: async bodies run via
`asyncio.run(...)` inside a plain sync `def test_...` (see `test_db.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.security import HTTPAuthorizationCredentials

import orchestrator.api.v1.dependencies.auth as auth_module
from orchestrator.api.v1.dependencies.auth import get_current_user, get_stream_user, require_role
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.security.jwt import create_access_token


def _make_user(role: UserRole = UserRole.MEMBER, is_active: bool = True) -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        hashed_password="irrelevant",
        role=role,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


class _FakeUserRepository:
    """Stand-in for `SqlAlchemyUserRepository`: returns a canned user by id."""

    def __init__(self, users_by_id: dict[uuid.UUID, User]) -> None:
        self._users_by_id = users_by_id

    def __call__(self, _session: object) -> _FakeUserRepository:
        return self

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._users_by_id.get(user_id)


def _patch_repository(monkeypatch: pytest.MonkeyPatch, users_by_id: dict[uuid.UUID, User]) -> None:
    monkeypatch.setattr(auth_module, "SqlAlchemyUserRepository", _FakeUserRepository(users_by_id))


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_get_current_user_returns_user_for_valid_token(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    _patch_repository(monkeypatch, {user.id: user})
    token = create_access_token(user)

    result = asyncio.run(get_current_user(credentials=_bearer(token), session=object()))

    assert result == user


def test_get_current_user_raises_401_for_malformed_token(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_repository(monkeypatch, {})

    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(get_current_user(credentials=_bearer("not-a-jwt"), session=object()))

    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_when_user_not_found(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    _patch_repository(monkeypatch, {})  # empty: user id from the token is unknown
    token = create_access_token(user)

    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(get_current_user(credentials=_bearer(token), session=object()))

    assert exc_info.value.status_code == 401


def test_get_current_user_raises_401_for_inactive_user(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user(is_active=False)
    _patch_repository(monkeypatch, {user.id: user})
    token = create_access_token(user)

    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(get_current_user(credentials=_bearer(token), session=object()))

    assert exc_info.value.status_code == 401


def test_require_role_admin_passes_a_valid_admin_user() -> None:
    admin = _make_user(role=UserRole.ADMIN)
    dependency = require_role(UserRole.ADMIN)

    result = asyncio.run(dependency(user=admin))

    assert result == admin


def test_require_role_member_gate_passes_for_admin_user_too() -> None:
    """D6: admin implicitly satisfies a `require_role(MEMBER)` check (rank: admin=2, member=1)."""
    admin = _make_user(role=UserRole.ADMIN)
    dependency = require_role(UserRole.MEMBER)

    result = asyncio.run(dependency(user=admin))

    assert result == admin


def test_require_role_admin_gate_raises_403_for_member_user() -> None:
    member = _make_user(role=UserRole.MEMBER)
    dependency = require_role(UserRole.ADMIN)

    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(dependency(user=member))

    assert exc_info.value.status_code == 403


class _FakeSessionCtx:
    """Stand-in for `get_session()`'s `@asynccontextmanager` — proves
    `get_stream_user` opens and closes its OWN short-lived session rather
    than depending on `get_db_session` (design D-Auth session hazard)."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> object:
        self.entered = True
        return object()

    async def __aexit__(self, *_exc_info: object) -> None:
        self.exited = True


def test_get_stream_user_prefers_the_header_over_the_query_token(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Threat matrix — credential exposure: the header path authenticates
    with zero query param present, proving the query fallback is
    browser-only, never mandatory."""
    user = _make_user()
    _patch_repository(monkeypatch, {user.id: user})
    fake_ctx = _FakeSessionCtx()
    monkeypatch.setattr(auth_module, "get_session", lambda: fake_ctx)
    token = create_access_token(user)

    result = asyncio.run(get_stream_user(credentials=_bearer(token), access_token=None))

    assert result == user
    assert fake_ctx.entered and fake_ctx.exited


def test_get_stream_user_falls_back_to_the_query_token_when_no_header(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    _patch_repository(monkeypatch, {user.id: user})
    monkeypatch.setattr(auth_module, "get_session", lambda: _FakeSessionCtx())
    token = create_access_token(user)

    result = asyncio.run(get_stream_user(credentials=None, access_token=token))

    assert result == user


def test_get_stream_user_raises_401_when_neither_header_nor_query_token_present(
    valid_env: None,
) -> None:
    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(get_stream_user(credentials=None, access_token=None))

    assert exc_info.value.status_code == 401


def test_get_stream_user_raises_401_for_an_expired_or_invalid_token(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_module, "get_session", lambda: _FakeSessionCtx())

    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(get_stream_user(credentials=_bearer("not-a-jwt"), access_token=None))

    assert exc_info.value.status_code == 401


def test_get_stream_user_closes_its_session_even_when_auth_fails(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the D-Auth session hazard: the short-lived
    session must be closed even on a 401, never left open."""
    fake_ctx = _FakeSessionCtx()
    monkeypatch.setattr(auth_module, "get_session", lambda: fake_ctx)
    _patch_repository(monkeypatch, {})

    with pytest.raises(ProblemException):
        asyncio.run(get_stream_user(credentials=_bearer("not-a-jwt"), access_token=None))

    assert fake_ctx.entered and fake_ctx.exited
