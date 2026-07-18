"""Alembic migration round-trip for tightening `findings.repository_id` to
`NOT NULL` (Module 7 PR3, task 4.11) against a live Postgres.

Spec scenario: `upgrade head` (through `072bb3e01833`) leaves
`repository_id` as `NOT NULL`; `first_seen_scan_run_id`/`last_seen_scan_run_id`
are unaffected (still nullable — `ON DELETE SET NULL`). `downgrade -1`
restores `repository_id` to nullable exactly as PR2's migration left it.
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


async def _findings_columns() -> dict[str, dict[str, object]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'findings'"
                )
            )
            return {row[0]: {"is_nullable": row[1]} for row in result}
    finally:
        await engine.dispose()


def test_upgrade_head_tightens_repository_id_to_not_null(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    try:
        columns = asyncio.run(_findings_columns())

        assert "repository_id" in columns
        assert columns["repository_id"]["is_nullable"] == "NO"

        # Unaffected by this migration — still SET NULL targets.
        assert columns["first_seen_scan_run_id"]["is_nullable"] == "YES"
        assert columns["last_seen_scan_run_id"]["is_nullable"] == "YES"
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_restores_repository_id_nullable(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "-1")
    try:
        columns = asyncio.run(_findings_columns())

        assert "repository_id" in columns
        assert columns["repository_id"]["is_nullable"] == "YES"
    finally:
        _run_alembic("downgrade", "base")
