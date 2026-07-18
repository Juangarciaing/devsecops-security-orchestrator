"""Additive Alembic migration round-trip for `findings.repository_id` /
`first_seen_scan_run_id` / `last_seen_scan_run_id` against a live Postgres.

Spec scenario (Module 7 D3): the new migration adds `repository_id`
(`ON DELETE CASCADE`) plus `first_seen_scan_run_id`/`last_seen_scan_run_id`
(`ON DELETE SET NULL`) on top of the existing `findings` table, and swaps
`UNIQUE(scan_task_id, fingerprint)` for `UNIQUE(repository_id, fingerprint)`;
downgrade restores the prior schema exactly. All 3 new columns stay nullable
in this PR2 migration — see the migration's own docstring for why
`repository_id` isn't tightened to `NOT NULL` until PR3/PR4 wires the write
path that guarantees a value on every insert.
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


async def _findings_unique_constraint_columns() -> set[frozenset[str]]:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT tc.constraint_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = 'findings'
                      AND tc.constraint_type = 'UNIQUE'
                    """
                )
            )
            by_constraint: dict[str, set[str]] = {}
            for constraint_name, column_name in result:
                by_constraint.setdefault(constraint_name, set()).add(column_name)
            return {frozenset(columns) for columns in by_constraint.values()}
    finally:
        await engine.dispose()


async def _findings_fk_ondelete_actions() -> dict[str, str]:
    """Map `constraint_name -> confdeltype` (`c`=CASCADE, `n`=SET NULL)."""
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT conname, confdeltype
                    FROM pg_constraint
                    WHERE conrelid = 'findings'::regclass AND contype = 'f'
                    """
                )
            )
            return {
                row[0]: (row[1].decode() if isinstance(row[1], bytes) else row[1]) for row in result
            }
    finally:
        await engine.dispose()


def test_upgrade_head_adds_repository_id_and_scan_run_tracking_columns(db_env: None) -> None:
    # Explicit own revision, NOT "head" — Module 7 PR3's `072bb3e01833`
    # becomes the new head and tightens `repository_id` to `NOT NULL`
    # (task 4.11), which would silently invalidate this PR2-scoped
    # "stays nullable" assertion if it tracked a moving `head` (same lesson
    # as `test_migration_add_credential_ref_is_active.py`, PR2).
    _run_alembic("upgrade", "9a4af6f0e9d0")
    try:
        columns = asyncio.run(_findings_columns())

        assert "repository_id" in columns
        # Stays nullable in PR2 — see migration docstring: the write path
        # that guarantees a value on every insert is PR3/PR4 scope.
        assert columns["repository_id"]["is_nullable"] == "YES"

        assert "first_seen_scan_run_id" in columns
        assert columns["first_seen_scan_run_id"]["is_nullable"] == "YES"

        assert "last_seen_scan_run_id" in columns
        assert columns["last_seen_scan_run_id"]["is_nullable"] == "YES"

        unique_sets = asyncio.run(_findings_unique_constraint_columns())
        assert frozenset({"repository_id", "fingerprint"}) in unique_sets
        assert frozenset({"scan_task_id", "fingerprint"}) not in unique_sets

        ondelete = asyncio.run(_findings_fk_ondelete_actions())
        assert "fk_findings_repository_id_code_repositories" in ondelete
        assert ondelete["fk_findings_repository_id_code_repositories"] == "c"
        assert ondelete["fk_findings_first_seen_scan_run_id_scan_runs"] == "n"
        assert ondelete["fk_findings_last_seen_scan_run_id_scan_runs"] == "n"
    finally:
        _run_alembic("downgrade", "base")


def test_downgrade_one_step_restores_prior_findings_schema(db_env: None) -> None:
    # Same "explicit own revision, not head" reasoning as the test above.
    _run_alembic("upgrade", "9a4af6f0e9d0")
    _run_alembic("downgrade", "-1")
    try:
        columns = asyncio.run(_findings_columns())

        assert "repository_id" not in columns
        assert "first_seen_scan_run_id" not in columns
        assert "last_seen_scan_run_id" not in columns

        unique_sets = asyncio.run(_findings_unique_constraint_columns())
        assert frozenset({"scan_task_id", "fingerprint"}) in unique_sets
        assert frozenset({"repository_id", "fingerprint"}) not in unique_sets
    finally:
        _run_alembic("downgrade", "base")
