"""`get_db_session` — plain async-gen wrapper making `get_session()` `Depends`-usable.

`get_session()` itself is `@asynccontextmanager`, which FastAPI's `Depends` cannot
consume directly. These tests stub `get_session` (no live Postgres needed) to prove
`get_db_session` forwards whatever `get_session()` yields, exactly once.

No `pytest-asyncio` plugin in this project (see `tests/integration/test_repositories.py`
for the established pattern): async test bodies run via `asyncio.run(...)` inside a
plain sync `def test_...`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from orchestrator.api.v1.dependencies.db import get_db_session


async def _yields_the_stubbed_session() -> None:
    sentinel_session = AsyncMock(name="fake-session")

    @asynccontextmanager
    async def fake_get_session() -> AsyncIterator[Any]:
        yield sentinel_session

    import orchestrator.api.v1.dependencies.db as db_module

    original = db_module.get_session
    db_module.get_session = fake_get_session
    try:
        generator = get_db_session()
        yielded = await anext(generator)

        assert yielded is sentinel_session

        with pytest.raises(StopAsyncIteration):
            await anext(generator)
    finally:
        db_module.get_session = original


def test_get_db_session_yields_the_session_from_get_session() -> None:
    asyncio.run(_yields_the_stubbed_session())


async def _each_call_gets_its_own_session() -> int:
    calls = 0

    @asynccontextmanager
    async def fake_get_session() -> AsyncIterator[str]:
        nonlocal calls
        calls += 1
        yield f"session-{calls}"

    import orchestrator.api.v1.dependencies.db as db_module

    original = db_module.get_session
    db_module.get_session = fake_get_session
    try:
        first_value = await anext(get_db_session())
        second_value = await anext(get_db_session())

        assert first_value == "session-1"
        assert second_value == "session-2"
    finally:
        db_module.get_session = original
    return calls


def test_get_db_session_calls_get_session_once_per_invocation() -> None:
    calls = asyncio.run(_each_call_gets_its_own_session())

    assert calls == 2
