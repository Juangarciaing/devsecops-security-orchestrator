"""Alembic migration round-trip for the `secrets-manager` PR2 schema change,
against a live Postgres.

Spec scenario ("Legacy non-null values are unusable"): any pre-existing
non-null `credential_ref` is nulled out before the column is dropped — it
was never encrypted and cannot be migrated in place. This module also
covers the additive/destructive shape of the rest of the migration:
`code_repositories` gains `credential_kind`/`credential_ciphertext` and
loses `credential_ref`; `scan_runs` gains `triggered_by_user_id`; the
`credential_access_log` table is created. Downgrade reverses all of it,
including dropping both new native enum types.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from orchestrator.infrastructure.db.engine import resolve_database_url

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]

_PRE_SECRETS_MANAGER_REVISION = "04c47c6921fb"


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _seed_legacy_repository_with_credential_ref(repository_id: uuid.UUID) -> None:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO code_repositories "
                    "(id, provider, owner, name, clone_url, default_branch, "
                    "credential_ref, is_active) "
                    "VALUES (:id, 'GITHUB', 'acme', 'legacy-widgets', "
                    "'https://github.com/acme/legacy-widgets.git', 'main', "
                    "'vault://secret/legacy-unusable', true)"
                ),
                {"id": repository_id},
            )
    finally:
        await engine.dispose()


async def _code_repositories_columns() -> dict[str, dict[str, object]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'code_repositories'"
                )
            )
            return {row[0]: {"is_nullable": row[1]} for row in result}
    finally:
        await engine.dispose()


async def _legacy_repository_credential_columns(
    repository_id: uuid.UUID,
) -> tuple[object, object]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT credential_kind, credential_ciphertext "
                    "FROM code_repositories WHERE id = :id"
                ),
                {"id": repository_id},
            )
            row = result.one()
            return row.credential_kind, row.credential_ciphertext
    finally:
        await engine.dispose()


def test_upgrade_nulls_legacy_credential_ref_before_dropping_it(db_env: None) -> None:
    """A pre-existing non-null `credential_ref` is unusable (never encrypted)
    and must not be migrated in place into the new ciphertext column."""
    repository_id = uuid.uuid4()
    _run_alembic("upgrade", _PRE_SECRETS_MANAGER_REVISION)
    try:
        asyncio.run(_seed_legacy_repository_with_credential_ref(repository_id))

        _run_alembic("upgrade", "a1f3c9d0e7b2")

        columns = asyncio.run(_code_repositories_columns())
        assert "credential_ref" not in columns
        assert "credential_kind" in columns
        assert "credential_ciphertext" in columns

        kind, ciphertext = asyncio.run(_legacy_repository_credential_columns(repository_id))
        assert kind is None
        assert ciphertext is None
    finally:
        _run_alembic("downgrade", "base")


def test_upgrade_adds_triggered_by_user_id_and_credential_access_log_table(
    db_env: None,
) -> None:
    _run_alembic("upgrade", "a1f3c9d0e7b2")
    try:
        engine = create_async_engine(resolve_database_url())

        async def _check() -> None:
            try:
                async with engine.connect() as connection:
                    scan_run_columns = {
                        row[0]
                        for row in (
                            await connection.execute(
                                text(
                                    "SELECT column_name FROM information_schema.columns "
                                    "WHERE table_schema = 'public' AND table_name = 'scan_runs'"
                                )
                            )
                        )
                    }
                    assert "triggered_by_user_id" in scan_run_columns

                    audit_columns = {
                        row[0]
                        for row in (
                            await connection.execute(
                                text(
                                    "SELECT column_name FROM information_schema.columns "
                                    "WHERE table_schema = 'public' "
                                    "AND table_name = 'credential_access_log'"
                                )
                            )
                        )
                    }
                    assert audit_columns == {
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

        asyncio.run(_check())
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_restores_credential_ref_and_drops_new_schema(
    db_env: None,
) -> None:
    _run_alembic("upgrade", "a1f3c9d0e7b2")
    _run_alembic("downgrade", "-1")
    try:
        columns = asyncio.run(_code_repositories_columns())
        assert "credential_ref" in columns
        assert columns["credential_ref"]["is_nullable"] == "YES"
        assert "credential_kind" not in columns
        assert "credential_ciphertext" not in columns

        engine = create_async_engine(resolve_database_url())

        async def _check_dropped() -> None:
            try:
                async with engine.connect() as connection:
                    tables = {
                        row[0]
                        for row in (
                            await connection.execute(
                                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                            )
                        )
                    }
                    assert "credential_access_log" not in tables

                    types = {
                        row[0]
                        for row in (
                            await connection.execute(
                                text(
                                    "SELECT typname FROM pg_type "
                                    "WHERE typname IN "
                                    "('credential_kind', 'credential_access_outcome')"
                                )
                            )
                        )
                    }
                    assert types == set()
            finally:
                await engine.dispose()

        asyncio.run(_check_dropped())
    finally:
        _run_alembic("downgrade", "base")
