# ruff: noqa: E501
"""Live Postgres proof for the polymorphic scan-subject migration."""

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


def _alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args], cwd=BACKEND_DIR, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


async def _prove_checks() -> None:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.begin() as connection:
            repository_id, target_id, run_id, task_id = (
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
            )
            await connection.execute(
                text(
                    "INSERT INTO code_repositories (id, provider, owner, name, clone_url, default_branch, is_active) VALUES (:id, 'GITHUB', 'owner', 'repo', 'https://example.test/repo.git', 'main', true)"
                ),
                {"id": repository_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO scan_targets (id, name, target_url, is_active) VALUES (:id, 'target', :url, true)"
                ),
                {"id": target_id, "url": f"https://{target_id}.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO scan_runs (id, repository_id, status, trigger, commit_sha, ref) VALUES (:id, :repo, 'PENDING', 'manual', 'sha', 'main')"
                ),
                {"id": run_id, "repo": repository_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO scan_tasks (id, scan_run_id, scanner_type, status) VALUES (:id, :run, 'SECRETS', 'PENDING')"
                ),
                {"id": task_id, "run": run_id},
            )
            for table, columns in (
                ("scan_runs", "id, status, trigger"),
                ("findings", "id, scan_task_id, severity, status, rule_id, title, fingerprint"),
            ):
                for repository, target in ((None, None), (repository_id, target_id)):
                    nested = await connection.begin_nested()
                    with pytest.raises(Exception, match=f"ck_{table}_exactly_one_subject"):
                        await connection.execute(
                            text(
                                f"INSERT INTO {table} ({columns}, repository_id, scan_target_id) VALUES (:id, "
                                + (
                                    "'PENDING', 'manual', "
                                    if table == "scan_runs"
                                    else "(SELECT id FROM scan_tasks LIMIT 1), 'HIGH', 'OPEN', 'r', 't', 'f', "
                                )
                                + ":repo, :target)"
                            ),
                            {"id": uuid.uuid4(), "repo": repository, "target": target},
                        )
                    await nested.rollback()
    finally:
        await engine.dispose()


def test_polymorphic_subject_migration_round_trip(db_env: None) -> None:
    _alembic("upgrade", "9afe58105f4e")
    try:
        _alembic("upgrade", "5e9b7a1c2d3e")
        asyncio.run(_prove_checks())
    finally:
        _alembic("downgrade", "base")
