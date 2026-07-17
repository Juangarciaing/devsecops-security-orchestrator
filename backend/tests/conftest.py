"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure get_settings() does not leak a cached Settings instance across tests."""
    from orchestrator.infrastructure.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate every required Settings env var with a valid placeholder value."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://orchestrator:changeme@localhost:5432/orchestrator"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key")
