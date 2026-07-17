"""Contract tests for `SqlAlchemyCodeRepositoryRepository` (first concrete
`CodeRepositoryPort` adapter) against a live Postgres.

DDL-level constraints (unique identity, cascade) are already proven in
`test_unique_constraints.py` / `test_cascade_delete.py`; these tests instead
prove the adapter correctly implements `CodeRepositoryPort`: round-trip
through the mappers, active-agnostic identity lookup, `list_active` filtering,
`update` mutating only mutable columns, and `soft_delete` idempotency.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    CodeRepositoryNotFoundError,
    SqlAlchemyCodeRepositoryRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches `created_at`/`updated_at` TZ-naive columns


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_ref": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


async def _create_get_list_roundtrip() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)

            created = await repository.create(
                _make_repository(owner="acme-crud", name="widgets-crud")
            )
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)

            by_id = await repository.get_by_id(created.id)
            assert by_id is not None
            assert by_id.owner == "acme-crud"
            assert by_id.is_active is True

            by_identity = await repository.get_by_identity(
                RepositoryProvider.GITHUB, "acme-crud", "widgets-crud"
            )
            assert by_identity is not None
            assert by_identity.id == created.id

            missing = await repository.get_by_id(uuid.uuid4())
            assert missing is None

            all_repos = await repository.list_all()
            assert any(r.id == created.id for r in all_repos)

            active_repos = await repository.list_active()
            assert any(r.id == created.id for r in active_repos)
    finally:
        await engine.dispose()


def test_create_get_by_id_get_by_identity_list_all_list_active(migrated_schema: None) -> None:
    asyncio.run(_create_get_list_roundtrip())


async def _get_by_identity_is_active_agnostic() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            created = await repository.create(
                _make_repository(owner="acme-identity", name="widgets-identity")
            )
            await repository.soft_delete(created.id)
            await session.commit()

            repo_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)

            by_identity = await repository.get_by_identity(
                RepositoryProvider.GITHUB, "acme-identity", "widgets-identity"
            )
            assert by_identity is not None
            assert by_identity.id == repo_id
            assert by_identity.is_active is False
    finally:
        await engine.dispose()


def test_get_by_identity_returns_inactive_matches(migrated_schema: None) -> None:
    asyncio.run(_get_by_identity_is_active_agnostic())


async def _list_active_excludes_inactive() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            active = await repository.create(
                _make_repository(owner="acme-list", name="active-repo")
            )
            inactive = await repository.create(
                _make_repository(owner="acme-list", name="inactive-repo")
            )
            await repository.soft_delete(inactive.id)
            await session.commit()

            active_id = active.id
            inactive_id = inactive.id

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)

            active_repos = await repository.list_active()
            active_ids = {r.id for r in active_repos}
            assert active_id in active_ids
            assert inactive_id not in active_ids

            all_repos = await repository.list_all()
            all_ids = {r.id for r in all_repos}
            assert active_id in all_ids
            assert inactive_id in all_ids
    finally:
        await engine.dispose()


def test_list_active_excludes_soft_deleted(migrated_schema: None) -> None:
    asyncio.run(_list_active_excludes_inactive())


async def _update_mutates_only_mutable_columns() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            created = await repository.create(
                _make_repository(owner="acme-update", name="widgets-update")
            )
            await session.commit()
            repo_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            to_update = await repository.get_by_id(repo_id)
            assert to_update is not None
            to_update.clone_url = "https://github.com/acme-update/widgets-update-new.git"
            to_update.default_branch = "develop"
            to_update.credential_ref = "vault://secret/widgets-update"

            updated = await repository.update(to_update)
            await session.commit()

            assert updated.clone_url == "https://github.com/acme-update/widgets-update-new.git"
            assert updated.default_branch == "develop"
            assert updated.credential_ref == "vault://secret/widgets-update"
            # Identity untouched.
            assert updated.owner == "acme-update"
            assert updated.name == "widgets-update"
            assert updated.updated_at >= created.updated_at

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            persisted = await repository.get_by_id(repo_id)
            assert persisted is not None
            assert persisted.clone_url == "https://github.com/acme-update/widgets-update-new.git"
    finally:
        await engine.dispose()


def test_update_mutates_only_mutable_columns(migrated_schema: None) -> None:
    asyncio.run(_update_mutates_only_mutable_columns())


async def _update_raises_not_found_for_missing_id() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            missing = _make_repository(id=uuid.uuid4())

            with pytest.raises(CodeRepositoryNotFoundError):
                await repository.update(missing)
    finally:
        await engine.dispose()


def test_update_raises_not_found_error_for_missing_id(migrated_schema: None) -> None:
    asyncio.run(_update_raises_not_found_for_missing_id())


async def _soft_delete_is_idempotent() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            created = await repository.create(
                _make_repository(owner="acme-soft-delete", name="widgets-soft-delete")
            )
            await session.commit()
            repo_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            await repository.soft_delete(repo_id)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            after_first = await repository.get_by_id(repo_id)
            assert after_first is not None
            assert after_first.is_active is False

            # Idempotent: calling again on an already-inactive repo is a no-op success.
            await repository.soft_delete(repo_id)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyCodeRepositoryRepository(session)
            after_second = await repository.get_by_id(repo_id)
            assert after_second is not None
            assert after_second.is_active is False

            # Idempotent: calling on a missing id does not raise.
            await repository.soft_delete(uuid.uuid4())
            await session.commit()
    finally:
        await engine.dispose()


def test_soft_delete_is_idempotent_and_missing_id_is_noop(migrated_schema: None) -> None:
    asyncio.run(_soft_delete_is_idempotent())
