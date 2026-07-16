"""Async session lifecycle helper.

`get_session()` is an async context manager (and a FastAPI-dependency-shaped
generator) that yields a single `AsyncSession` per request/unit of work, using
the process-wide cached sessionmaker from `engine.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.infrastructure.db.engine import get_sessionmaker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an `AsyncSession`, committing on success and rolling back on error."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
