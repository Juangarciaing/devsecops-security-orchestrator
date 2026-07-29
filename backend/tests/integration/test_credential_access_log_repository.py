"""Contract tests for `SqlAlchemyCredentialAccessLogRepository` against a live
Postgres.

DDL-level constraints are proven by the migration itself (schema shape
verified inline below); this file proves the repository adapter correctly
implements `CredentialAccessLogPort.append()` — persists an append-only row
using only the allowlisted columns (repository/scan/kind/actor/outcome/
timestamp), never a plaintext or ciphertext credential value, which the
`CredentialAccessLog` entity has no field for in the first place.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.credential_access_log import CredentialAccessLog
from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.credential_access_log_repository import (
    SqlAlchemyCredentialAccessLogRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC).replace(tzinfo=None)


async def _append_and_read_back() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        entry_id = uuid.uuid4()
        repository_id = uuid.uuid4()
        scan_task_id = uuid.uuid4()

        async with sessionmaker() as session:
            repository = SqlAlchemyCredentialAccessLogRepository(session)
            await repository.append(
                CredentialAccessLog(
                    id=entry_id,
                    repository_id=repository_id,
                    scan_task_id=scan_task_id,
                    credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
                    actor="webhook",
                    outcome=CredentialAccessOutcome.USED,
                    accessed_at=_NOW,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT repository_id, scan_task_id, credential_kind, actor, "
                        "actor_user_id, outcome FROM credential_access_log WHERE id = :id"
                    ),
                    {"id": entry_id},
                )
            ).one()
            assert row.repository_id == repository_id
            assert row.scan_task_id == scan_task_id
            assert row.credential_kind == "PERSONAL_ACCESS_TOKEN"
            assert row.actor == "webhook"
            assert row.actor_user_id is None
            assert row.outcome == "USED"

            columns = (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'credential_access_log'"
                    )
                )
            ).scalars()
            assert set(columns) == {
                "id",
                "repository_id",
                "scan_task_id",
                "credential_kind",
                "actor",
                "actor_user_id",
                "outcome",
                "accessed_at",
            }
    finally:
        await engine.dispose()


def test_append_persists_only_allowlisted_columns(migrated_schema: None) -> None:
    asyncio.run(_append_and_read_back())


async def _append_manual_actor() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        entry_id = uuid.uuid4()
        actor_user_id = uuid.uuid4()

        async with sessionmaker() as session:
            repository = SqlAlchemyCredentialAccessLogRepository(session)
            await repository.append(
                CredentialAccessLog(
                    id=entry_id,
                    repository_id=uuid.uuid4(),
                    credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
                    actor="jane@example.com",
                    actor_user_id=actor_user_id,
                    outcome=CredentialAccessOutcome.DECRYPT_FAILED,
                    accessed_at=_NOW,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT scan_task_id, actor, actor_user_id, outcome "
                        "FROM credential_access_log WHERE id = :id"
                    ),
                    {"id": entry_id},
                )
            ).one()
            assert row.scan_task_id is None
            assert row.actor == "jane@example.com"
            assert row.actor_user_id == actor_user_id
            assert row.outcome == "DECRYPT_FAILED"
    finally:
        await engine.dispose()


def test_append_persists_manual_actor_and_decrypt_failed_outcome(
    migrated_schema: None,
) -> None:
    asyncio.run(_append_manual_actor())
