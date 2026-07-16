"""Unit tests for the async engine factory's DSN normalization.

These tests exercise only the pure DSN-normalization logic, not the actual
`create_async_engine(...)` call — building a real async engine against the
`postgresql+asyncpg://` scheme requires the `asyncpg` driver to be importable,
which is only added to `pyproject.toml` in PR4 (Alembic wiring). Testing the
normalization function directly keeps this unit test dependency-free.
"""

from __future__ import annotations

import pytest

from orchestrator.infrastructure.db import engine as engine_module


class _FakeSettings:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def test_bare_postgresql_dsn_is_normalized_to_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        engine_module,
        "get_settings",
        lambda: _FakeSettings("postgresql://orchestrator:changeme@localhost:5432/orchestrator"),
    )

    resolved = engine_module.resolve_database_url()

    assert resolved == "postgresql+asyncpg://orchestrator:changeme@localhost:5432/orchestrator"


def test_already_asyncpg_dsn_is_left_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        engine_module,
        "get_settings",
        lambda: _FakeSettings(
            "postgresql+asyncpg://orchestrator:changeme@localhost:5432/orchestrator"
        ),
    )

    resolved = engine_module.resolve_database_url()

    assert resolved == "postgresql+asyncpg://orchestrator:changeme@localhost:5432/orchestrator"


def test_non_postgresql_dsn_is_left_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        engine_module,
        "get_settings",
        lambda: _FakeSettings("sqlite:///:memory:"),
    )

    resolved = engine_module.resolve_database_url()

    assert resolved == "sqlite:///:memory:"
