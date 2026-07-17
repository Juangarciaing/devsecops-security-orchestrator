"""`authenticate_user` use case — email/password verification against `UserPort`.

Fake `UserPort` (in-memory dict), no live Postgres needed. No `pytest-asyncio`
plugin in this project — async bodies run via `asyncio.run(...)` (established
PR3 convention, see `tests/unit/api/dependencies/test_auth.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.authenticate_user import (
    InvalidCredentialsError,
    authenticate_user,
)
from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.security.password_hasher import hash_password


class _FakeUserRepository(UserPort):
    def __init__(self, users_by_email: dict[str, User]) -> None:
        self._users_by_email = users_by_email

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        raise NotImplementedError

    async def get_by_email(self, email: str) -> User | None:
        return self._users_by_email.get(email)

    async def create(self, user: User) -> User:
        raise NotImplementedError

    async def list_all(self) -> list[User]:
        raise NotImplementedError


def _make_user(email: str, password: str, *, is_active: bool = True) -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.MEMBER,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def test_authenticate_user_returns_user_for_correct_credentials() -> None:
    user = _make_user("member@example.com", "correct-horse")
    repository = _FakeUserRepository({user.email: user})

    result = asyncio.run(authenticate_user(repository, "member@example.com", "correct-horse"))

    assert result == user


def test_authenticate_user_raises_for_wrong_password() -> None:
    user = _make_user("member@example.com", "correct-horse")
    repository = _FakeUserRepository({user.email: user})

    try:
        asyncio.run(authenticate_user(repository, "member@example.com", "wrong-password"))
        raise AssertionError("expected InvalidCredentialsError")
    except InvalidCredentialsError:
        pass


def test_authenticate_user_raises_for_unknown_email() -> None:
    repository = _FakeUserRepository({})

    try:
        asyncio.run(authenticate_user(repository, "nobody@example.com", "irrelevant"))
        raise AssertionError("expected InvalidCredentialsError")
    except InvalidCredentialsError:
        pass


def test_authenticate_user_raises_for_inactive_user() -> None:
    user = _make_user("member@example.com", "correct-horse", is_active=False)
    repository = _FakeUserRepository({user.email: user})

    try:
        asyncio.run(authenticate_user(repository, "member@example.com", "correct-horse"))
        raise AssertionError("expected InvalidCredentialsError")
    except InvalidCredentialsError:
        pass
