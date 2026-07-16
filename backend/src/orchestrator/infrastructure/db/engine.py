"""Async SQLAlchemy engine/sessionmaker factories.

`Settings.database_url` (Module 1, frozen) is a plain sync-style
`postgresql://...` DSN. `resolve_database_url()` normalizes it to the
`postgresql+asyncpg://...` scheme SQLAlchemy's async engine requires, without
touching `Settings` itself.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orchestrator.infrastructure.config.settings import get_settings

_SYNC_SCHEME = "postgresql://"
_ASYNC_SCHEME = "postgresql+asyncpg://"


def normalize_async_dsn(database_url: str) -> str:
    """Normalize a bare `postgresql://` DSN to the asyncpg-driver scheme.

    Already-qualified DSNs (`postgresql+asyncpg://...`) and DSNs for other
    schemes (e.g. `sqlite://...`) are returned unchanged.
    """
    if database_url.startswith(_SYNC_SCHEME) and not database_url.startswith(_ASYNC_SCHEME):
        return _ASYNC_SCHEME + database_url[len(_SYNC_SCHEME) :]
    return database_url


def resolve_database_url() -> str:
    """Read `Settings.database_url` and normalize it for the async engine."""
    return normalize_async_dsn(get_settings().database_url)


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide cached async engine."""
    return create_async_engine(resolve_database_url())


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide cached async session factory."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)
