"""Additive Alembic migration round-trip for `code_repositories` against a
live Postgres.

Spec scenario: the new migration adds `credential_ref` (nullable) and
`is_active` (not-null, `server_default=true`) on top of the existing
`code_repositories` table; downgrade drops both columns cleanly.
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


async def _code_repositories_columns() -> dict[str, dict[str, object]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'code_repositories'"
                )
            )
            return {row[0]: {"is_nullable": row[1], "column_default": row[2]} for row in result}
    finally:
        await engine.dispose()


def test_upgrade_head_adds_credential_ref_and_is_active_columns(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    try:
        columns = asyncio.run(_code_repositories_columns())

        assert "credential_ref" in columns
        assert columns["credential_ref"]["is_nullable"] == "YES"

        assert "is_active" in columns
        assert columns["is_active"]["is_nullable"] == "NO"
        assert columns["is_active"]["column_default"] is not None
        assert "true" in str(columns["is_active"]["column_default"]).lower()
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_drops_credential_ref_and_is_active_columns(db_env: None) -> None:
    # Target this migration's own revision explicitly, then step back one —
    # `downgrade -1` *from head* would instead undo whatever the newest
    # migration happens to be (e.g. Module 7 PR2's `findings` migration),
    # not this one.
    _run_alembic("upgrade", "04c47c6921fb")
    _run_alembic("downgrade", "-1")
    try:
        columns = asyncio.run(_code_repositories_columns())

        assert "credential_ref" not in columns
        assert "is_active" not in columns
    finally:
        _run_alembic("downgrade", "base")
