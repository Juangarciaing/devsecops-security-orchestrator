"""Shared fixtures for integration tests that need a live Postgres.

`docker-compose.override.yml` publishes the `postgres` service's 5432 port to
the host for local dev, so `localhost:5432` is reachable once
`docker compose up -d postgres` reports healthy.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
_LIVE_DATABASE_URL = "postgresql://orchestrator:changeme@localhost:5432/orchestrator"


@pytest.fixture
def db_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point `Settings.database_url` at the live Postgres container for this test."""
    monkeypatch.setenv("DATABASE_URL", _LIVE_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key")

    from orchestrator.infrastructure.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def migrated_schema(db_env: None) -> Iterator[None]:
    """Apply the baseline migration before the test, roll it back after.

    Gives each DB-backed test (cascade delete, unique constraints) a clean,
    isolated schema without depending on test execution order.
    """
    _run_alembic("upgrade", "head")
    yield
    _run_alembic("downgrade", "base")
