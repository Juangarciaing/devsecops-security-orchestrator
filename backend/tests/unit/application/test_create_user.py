"""`create_user` use case — hashes the password, rejects duplicate emails."""

from __future__ import annotations

import asyncio
import uuid

from orchestrator.application.use_cases.create_user import DuplicateEmailError, create_user
from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.security.password_hasher import verify_password


class _FakeUserRepository(UserPort):
    def __init__(self) -> None:
        self.created: list[User] = []
        self._users_by_email: dict[str, User] = {}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        raise NotImplementedError

    async def get_by_email(self, email: str) -> User | None:
        return self._users_by_email.get(email)

    async def create(self, user: User) -> User:
        self._users_by_email[user.email] = user
        self.created.append(user)
        return user

    async def list_all(self) -> list[User]:
        return list(self._users_by_email.values())


def test_create_user_hashes_password_and_defaults_to_member() -> None:
    repository = _FakeUserRepository()

    created = asyncio.run(create_user(repository, "new@example.com", "s3cret-passw0rd"))

    assert created.email == "new@example.com"
    assert created.role is UserRole.MEMBER
    assert created.hashed_password != "s3cret-passw0rd"
    assert verify_password("s3cret-passw0rd", created.hashed_password)


def test_create_user_honors_explicit_admin_role() -> None:
    repository = _FakeUserRepository()

    created = asyncio.run(
        create_user(repository, "admin@example.com", "s3cret-passw0rd", role=UserRole.ADMIN)
    )

    assert created.role is UserRole.ADMIN


def test_create_user_raises_on_duplicate_email() -> None:
    repository = _FakeUserRepository()
    asyncio.run(create_user(repository, "dup@example.com", "first-password"))

    try:
        asyncio.run(create_user(repository, "dup@example.com", "second-password"))
        raise AssertionError("expected DuplicateEmailError")
    except DuplicateEmailError:
        pass

    assert len(repository.created) == 1
