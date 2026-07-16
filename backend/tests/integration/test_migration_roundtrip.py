"""Alembic migration round-trip against a live Postgres.

Spec scenario: `alembic upgrade head` creates all 4 tables; `alembic
downgrade base` returns the schema to empty. Shells out to the real
`alembic` CLI (the same commands an operator runs) rather than importing
`env.py` directly, so this exercises the actual entrypoint end to end.
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
_EXPECTED_TABLES = {"code_repositories", "scan_runs", "scan_tasks", "findings"}


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _table_names() -> set[str]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
                {"s": "public"},
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


def test_upgrade_head_creates_all_four_tables(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    try:
        tables = asyncio.run(_table_names())
        assert _EXPECTED_TABLES <= tables
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_base_removes_all_domain_tables(db_env: None) -> None:
    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "base")

    tables = asyncio.run(_table_names())
    assert tables.isdisjoint(_EXPECTED_TABLES)
