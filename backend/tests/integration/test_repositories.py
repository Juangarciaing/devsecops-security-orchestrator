"""Contract tests for the first concrete `*Port` adapters against a live
Postgres: `SqlAlchemyUserRepository` and `SqlAlchemyApiKeyRepository`.

DDL-level constraints are already proven in `test_cascade_delete.py` /
`test_unique_constraints.py`; these tests instead prove the repository
adapters correctly implement `UserPort` / `ApiKeyPort` (round-trip through
the mappers, `None` on miss, mutation methods persist).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.api_key_repository import (
    SqlAlchemyApiKeyRepository,
)
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: `users`/`api_keys` timestamp columns are TZ-naive


async def _user_repository_roundtrip() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyUserRepository(session)

            created = await repository.create(
                User(
                    id=uuid.uuid4(),
                    email="repo-user@example.com",
                    hashed_password="hashed",
                    role=UserRole.ADMIN,
                    is_active=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyUserRepository(session)

            by_id = await repository.get_by_id(created.id)
            assert by_id is not None
            assert by_id.email == "repo-user@example.com"
            assert by_id.role == UserRole.ADMIN

            by_email = await repository.get_by_email("repo-user@example.com")
            assert by_email is not None
            assert by_email.id == created.id

            missing = await repository.get_by_email("nobody@example.com")
            assert missing is None

            all_users = await repository.list_all()
            assert any(u.id == created.id for u in all_users)
    finally:
        await engine.dispose()


def test_user_repository_create_get_by_id_get_by_email_list_all(migrated_schema: None) -> None:
    asyncio.run(_user_repository_roundtrip())


async def _api_key_repository_roundtrip() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            user_repository = SqlAlchemyUserRepository(session)
            user = await user_repository.create(
                User(
                    id=uuid.uuid4(),
                    email="key-owner-repo@example.com",
                    hashed_password="hashed",
                    role=UserRole.MEMBER,
                    is_active=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.flush()

            api_key_repository = SqlAlchemyApiKeyRepository(session)
            created = await api_key_repository.create(
                ApiKey(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    key_prefix="dso_repotest",
                    hashed_key="hashed-secret",
                    created_at=_NOW,
                )
            )
            await session.commit()

            user_id = user.id
            key_id = created.id

        async with sessionmaker() as session:
            api_key_repository = SqlAlchemyApiKeyRepository(session)

            by_prefix = await api_key_repository.get_by_prefix("dso_repotest")
            assert by_prefix is not None
            assert by_prefix.user_id == user_id
            assert by_prefix.is_active is True

            for_user = await api_key_repository.list_for_user(user_id)
            assert any(k.id == key_id for k in for_user)

            touched = await api_key_repository.touch(key_id)
            assert touched.last_used_at is not None
            await session.commit()

        async with sessionmaker() as session:
            api_key_repository = SqlAlchemyApiKeyRepository(session)

            revoked = await api_key_repository.revoke(key_id)
            assert revoked.revoked_at is not None
            assert revoked.is_active is False
            await session.commit()

        async with sessionmaker() as session:
            api_key_repository = SqlAlchemyApiKeyRepository(session)
            persisted = await api_key_repository.get_by_prefix("dso_repotest")
            assert persisted is not None
            assert persisted.is_active is False
    finally:
        await engine.dispose()


def test_api_key_repository_create_get_list_touch_revoke(migrated_schema: None) -> None:
    asyncio.run(_api_key_repository_roundtrip())
