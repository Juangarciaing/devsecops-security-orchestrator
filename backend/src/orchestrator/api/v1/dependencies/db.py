"""`get_db_session` — `Depends`-usable wrapper around `get_session()`.

`get_session()` (see `infrastructure/db/session.py`) is `@asynccontextmanager`,
which FastAPI's `Depends` cannot consume directly despite its
generator-shaped docstring. `get_db_session` is a plain async generator that
delegates the commit/rollback lifecycle to `get_session()`, making it usable
as `session: AsyncSession = Depends(get_db_session)`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.infrastructure.db.session import get_session


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a single `AsyncSession` per request, delegating to `get_session()`."""
    async with get_session() as session:
        yield session
