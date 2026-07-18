"""`run_async` — throwaway `NullPool` per-task session helper for Celery workers (D2).

Celery task execution happens outside any asyncio event loop, and each task
invocation needs its own. The process-wide cached async engine
(`infrastructure.db.engine.get_engine`) is unsuitable here: its asyncpg
connection pool binds to the loop that created it, and `asyncio.run` closes
that loop when the call returns — a second task invocation would then hit a
"Task attached to a different loop" error against the stale pooled
connections.

Building a throwaway `NullPool` engine per call and disposing it in `finally`
sidesteps this entirely: no pooled connections outlive a single
`asyncio.run`. Fine for a skeleton no-op task; a persistent-loop worker
optimization is deferred.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from orchestrator.infrastructure.db.engine import resolve_database_url


def run_async[T](coro_factory: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run `coro_factory(session)` to completion on a fresh event loop/engine.

    `coro_factory` receives one `AsyncSession` bound to a throwaway
    `NullPool` engine. The engine is disposed in `finally` regardless of
    outcome (D2).
    """

    async def _run() -> T:
        engine = create_async_engine(resolve_database_url(), poolclass=NullPool)
        try:
            sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
            async with sessionmaker() as session:
                return await coro_factory(session)
        finally:
            await engine.dispose()

    return asyncio.run(_run())
