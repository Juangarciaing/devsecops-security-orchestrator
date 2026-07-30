"""Alembic migration round-trip for the `dast-scanner` PR1 schema change
(`scan_targets` table), against a live Postgres.

Mirrors `test_migration_add_encrypted_credentials.py`'s shape: assert the
table/columns exist after upgrade, and that everything is cleanly dropped on
downgrade — no dependents exist yet (confirmed: `ScanTarget` has no linkage
to any other table in this slice), so downgrade is a plain `DROP TABLE`.
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

_PRE_DAST_SCANNER_REVISION = "a1f3c9d0e7b2"


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _scan_targets_columns() -> dict[str, dict[str, object]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'scan_targets'"
                )
            )
            return {row[0]: {"is_nullable": row[1]} for row in result}
    finally:
        await engine.dispose()


async def _tables() -> set[str]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


def test_upgrade_creates_scan_targets_table_with_expected_columns(db_env: None) -> None:
    _run_alembic("upgrade", _PRE_DAST_SCANNER_REVISION)
    try:
        _run_alembic("upgrade", "9afe58105f4e")

        columns = asyncio.run(_scan_targets_columns())
        assert columns["id"]["is_nullable"] == "NO"
        assert columns["name"]["is_nullable"] == "NO"
        assert columns["target_url"]["is_nullable"] == "NO"
        assert columns["is_active"]["is_nullable"] == "NO"
        assert columns["created_at"]["is_nullable"] == "NO"
        assert columns["updated_at"]["is_nullable"] == "NO"
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_drops_scan_targets_table(db_env: None) -> None:
    _run_alembic("upgrade", "9afe58105f4e")
    _run_alembic("downgrade", "-1")
    try:
        tables = asyncio.run(_tables())
        assert "scan_targets" not in tables
    finally:
        _run_alembic("downgrade", "base")
