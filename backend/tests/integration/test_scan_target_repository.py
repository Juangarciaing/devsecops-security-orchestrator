"""Contract tests for `SqlAlchemyScanTargetRepository` (dast-scanner PR1's
first concrete `ScanTargetPort` adapter) against a live Postgres.

Mirrors `test_code_repository_repository.py`'s shape: round-trip through the
mappers, `get_by_url` lookup, `list_active` filtering, `update` mutating only
mutable columns, and `soft_delete` idempotency.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    ScanTargetNotFoundError,
    SqlAlchemyScanTargetRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches `created_at`/`updated_at` TZ-naive columns


def _make_target(**overrides: object) -> ScanTarget:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "acme-public-site",
        "target_url": "https://example.com/acme-public-site",
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return ScanTarget(**defaults)  # type: ignore[arg-type]


async def _create_get_list_roundtrip() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)

            created = await repository.create(
                _make_target(name="acme-crud", target_url="https://example.com/acme-crud")
            )
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)

            by_id = await repository.get_by_id(created.id)
            assert by_id is not None
            assert by_id.name == "acme-crud"
            assert by_id.is_active is True

            by_url = await repository.get_by_url("https://example.com/acme-crud")
            assert by_url is not None
            assert by_url.id == created.id

            missing = await repository.get_by_id(uuid.uuid4())
            assert missing is None

            all_targets = await repository.list_all()
            assert any(t.id == created.id for t in all_targets)

            active_targets = await repository.list_active()
            assert any(t.id == created.id for t in active_targets)
    finally:
        await engine.dispose()


def test_create_get_by_id_get_by_url_list_all_list_active(migrated_schema: None) -> None:
    asyncio.run(_create_get_list_roundtrip())


async def _get_by_url_is_active_agnostic() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            created = await repository.create(
                _make_target(name="acme-identity", target_url="https://example.com/acme-identity")
            )
            await repository.soft_delete(created.id)
            await session.commit()

            target_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)

            by_url = await repository.get_by_url("https://example.com/acme-identity")
            assert by_url is not None
            assert by_url.id == target_id
            assert by_url.is_active is False
    finally:
        await engine.dispose()


def test_get_by_url_returns_inactive_matches(migrated_schema: None) -> None:
    asyncio.run(_get_by_url_is_active_agnostic())


async def _list_active_excludes_inactive() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            active = await repository.create(
                _make_target(name="active-target", target_url="https://example.com/active-target")
            )
            inactive = await repository.create(
                _make_target(
                    name="inactive-target",
                    target_url="https://example.com/inactive-target",
                )
            )
            await repository.soft_delete(inactive.id)
            await session.commit()

            active_id = active.id
            inactive_id = inactive.id

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)

            active_targets = await repository.list_active()
            active_ids = {t.id for t in active_targets}
            assert active_id in active_ids
            assert inactive_id not in active_ids

            all_targets = await repository.list_all()
            all_ids = {t.id for t in all_targets}
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
            repository = SqlAlchemyScanTargetRepository(session)
            created = await repository.create(
                _make_target(name="acme-update", target_url="https://example.com/acme-update")
            )
            await session.commit()
            target_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            to_update = await repository.get_by_id(target_id)
            assert to_update is not None
            to_update.name = "acme-update-renamed"
            to_update.target_url = "https://example.com/acme-update-new"

            updated = await repository.update(to_update)
            await session.commit()

            assert updated.name == "acme-update-renamed"
            assert updated.target_url == "https://example.com/acme-update-new"
            assert updated.updated_at >= created.updated_at

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            persisted = await repository.get_by_id(target_id)
            assert persisted is not None
            assert persisted.target_url == "https://example.com/acme-update-new"
    finally:
        await engine.dispose()


def test_update_mutates_only_mutable_columns(migrated_schema: None) -> None:
    asyncio.run(_update_mutates_only_mutable_columns())


async def _update_raises_not_found_for_missing_id() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            missing = _make_target(id=uuid.uuid4())

            with pytest.raises(ScanTargetNotFoundError):
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
            repository = SqlAlchemyScanTargetRepository(session)
            created = await repository.create(
                _make_target(
                    name="acme-soft-delete",
                    target_url="https://example.com/acme-soft-delete",
                )
            )
            await session.commit()
            target_id = created.id

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            await repository.soft_delete(target_id)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            after_first = await repository.get_by_id(target_id)
            assert after_first is not None
            assert after_first.is_active is False

            # Idempotent: calling again on an already-inactive target is a no-op success.
            await repository.soft_delete(target_id)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyScanTargetRepository(session)
            after_second = await repository.get_by_id(target_id)
            assert after_second is not None
            assert after_second.is_active is False

            # Idempotent: calling on a missing id does not raise.
            await repository.soft_delete(uuid.uuid4())
            await session.commit()
    finally:
        await engine.dispose()


def test_soft_delete_is_idempotent_and_missing_id_is_noop(migrated_schema: None) -> None:
    asyncio.run(_soft_delete_is_idempotent())
