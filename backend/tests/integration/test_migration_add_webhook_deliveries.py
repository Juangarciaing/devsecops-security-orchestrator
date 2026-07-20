"""Alembic migration round-trip for `webhook_deliveries` against a live
Postgres.

Spec scenario: additive migration on top of `072bb3e01833` creates the
`webhook_deliveries` table (nullable+`UNIQUE` `delivery_id`, `NOT NULL`
`signature_valid`/`outcome`/`received_at`) plus the native `webhook_outcome`
enum type; downgrading back to this migration's own `down_revision` drops both
cleanly, leaving no orphaned enum type behind (mirrors the baseline/`user_role`
migration's manual `DROP TYPE`).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from orchestrator.infrastructure.db.engine import resolve_database_url

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _webhook_deliveries_columns() -> dict[str, dict[str, object]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'webhook_deliveries'"
                )
            )
            return {row[0]: {"is_nullable": row[1]} for row in result}
    finally:
        await engine.dispose()


async def _table_exists(table_name: str) -> bool:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT to_regclass(:qualified_name) IS NOT NULL"),
                {"qualified_name": f"public.{table_name}"},
            )
            return bool(result.scalar())
    finally:
        await engine.dispose()


async def _enum_type_exists(type_name: str) -> bool:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT 1 FROM pg_type WHERE typname = :type_name"),
                {"type_name": type_name},
            )
            return result.first() is not None
    finally:
        await engine.dispose()


def test_upgrade_head_creates_webhook_deliveries_table(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    try:
        columns = asyncio.run(_webhook_deliveries_columns())

        assert columns["delivery_id"]["is_nullable"] == "YES"
        assert columns["signature_valid"]["is_nullable"] == "NO"
        assert columns["outcome"]["is_nullable"] == "NO"
        assert columns["received_at"]["is_nullable"] == "NO"
        assert asyncio.run(_enum_type_exists("webhook_outcome")) is True
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_drops_table_and_enum_type(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    # Target the webhook migration's own down_revision explicitly rather than
    # "-1": later migrations (e.g. `2d367959d214`, adding `SEMGREP` to the
    # `scanner_type` enum) may stack on top of head, so "-1" from head no
    # longer necessarily reverts THIS migration.
    _run_alembic("downgrade", "072bb3e01833")
    try:
        assert asyncio.run(_table_exists("webhook_deliveries")) is False
        assert asyncio.run(_enum_type_exists("webhook_outcome")) is False
    finally:
        _run_alembic("downgrade", "base")
