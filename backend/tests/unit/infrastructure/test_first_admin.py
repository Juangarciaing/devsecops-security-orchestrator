"""`bootstrap_first_admin` (D7) — idempotent first-admin seeding.

Core check-and-create logic is pure `UserPort`-driven, so it's tested here
with a fake in-memory port — no live Postgres needed. Running it twice must
NOT create a second admin.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.bootstrap.first_admin import bootstrap_first_admin
from orchestrator.infrastructure.security.password_hasher import verify_password


class _FakeUserRepository(UserPort):
    def __init__(self, seed: list[User] | None = None) -> None:
        self._users: list[User] = list(seed or [])

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return next((u for u in self._users if u.id == user_id), None)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users if u.email == email), None)

    async def create(self, user: User) -> User:
        self._users.append(user)
        return user

    async def list_all(self) -> list[User]:
        return list(self._users)


def _existing_member() -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    return User(
        id=uuid.uuid4(),
        email="member@example.com",
        hashed_password="irrelevant",
        role=UserRole.MEMBER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_bootstrap_creates_admin_when_none_exists() -> None:
    repository = _FakeUserRepository(seed=[_existing_member()])

    created = asyncio.run(
        bootstrap_first_admin(repository, email="admin@example.com", password="s3cret-passw0rd")
    )

    assert created is not None
    assert created.role is UserRole.ADMIN
    assert verify_password("s3cret-passw0rd", created.hashed_password)


def test_bootstrap_is_idempotent_running_twice_creates_only_one_admin() -> None:
    repository = _FakeUserRepository()

    first = asyncio.run(
        bootstrap_first_admin(repository, email="admin@example.com", password="s3cret-passw0rd")
    )
    second = asyncio.run(
        bootstrap_first_admin(repository, email="admin@example.com", password="s3cret-passw0rd")
    )

    assert first is not None
    assert second is None
    all_users = asyncio.run(repository.list_all())
    admins = [u for u in all_users if u.role is UserRole.ADMIN]
    assert len(admins) == 1


def test_bootstrap_skips_when_email_or_password_missing() -> None:
    repository = _FakeUserRepository()

    result_no_email = asyncio.run(
        bootstrap_first_admin(repository, email=None, password="s3cret-passw0rd")
    )
    result_no_password = asyncio.run(
        bootstrap_first_admin(repository, email="admin@example.com", password=None)
    )

    assert result_no_email is None
    assert result_no_password is None
    assert asyncio.run(repository.list_all()) == []


def test_bootstrap_skips_when_an_admin_already_exists_even_with_different_email() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    existing_admin = User(
        id=uuid.uuid4(),
        email="existing-admin@example.com",
        hashed_password="irrelevant",
        role=UserRole.ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    repository = _FakeUserRepository(seed=[existing_admin])

    result = asyncio.run(
        bootstrap_first_admin(repository, email="new-admin@example.com", password="s3cret-passw0rd")
    )

    assert result is None
    all_users = asyncio.run(repository.list_all())
    assert len(all_users) == 1
