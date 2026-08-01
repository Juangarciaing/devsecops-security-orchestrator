"""`ScanEventRelay` — ONE process-wide Redis pub/sub subscription (design
D-PubSub), fanning out in-process to per-connection `asyncio.Queue`s.

Client connect/disconnect is a pure dict mutation; no Redis round-trip is
ever made per client, so a closed browser tab cannot leak a Redis
subscription — there is only one, for the process's lifetime.

App-scoped (`app.state.scan_event_relay`), NOT a module global — a
deliberate deviation from `tracing.py`'s precedent (see design): a relay
holding a live socket and a background task must be per-`create_app()`
instance, or two test apps would share one Redis connection. `start()`/
`stop()` are wired into `_lifespan` alongside `shutdown_tracing()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis_asyncio

from orchestrator.infrastructure.config.settings import Settings, get_settings
from orchestrator.infrastructure.realtime.channels import (
    SCAN_EVENTS_PATTERN,
    scan_run_id_from_channel,
)

logger = logging.getLogger(__name__)

_MAX_QUEUED_EVENTS = 16
_GET_MESSAGE_TIMEOUT_SECONDS = 1.0


class ScanEventRelay:
    """One Redis client, one `PubSub`, one reader task, N in-process queues."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        redis_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._redis_client_factory = redis_client_factory
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._reader: asyncio.Task[None] | None = None
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = {}

    async def start(self) -> None:
        """No-op when `realtime_enabled` is False (design D-Gate): no client,
        no `PubSub`, no background task, no socket."""
        if self._redis_client_factory is not None:
            self._redis = self._redis_client_factory()
        else:
            settings = self._settings or get_settings()
            if not settings.realtime_enabled:
                return
            self._redis = redis_asyncio.Redis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(SCAN_EVENTS_PATTERN)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        pubsub = self._pubsub
        assert pubsub is not None  # only scheduled by start() after self._pubsub is set
        while True:
            msg = await pubsub.get_message(timeout=_GET_MESSAGE_TIMEOUT_SECONDS)
            if msg is None:
                continue
            scan_run_id = scan_run_id_from_channel(msg["channel"])
            for queue in tuple(self._subscribers.get(scan_run_id, ())):
                try:
                    queue.put_nowait(msg["data"])
                except asyncio.QueueFull:
                    pass  # a slow client NEVER blocks the shared reader (D3 best-effort)

    @asynccontextmanager
    async def subscribe(self, scan_run_id: str) -> AsyncIterator[asyncio.Queue[str]]:
        """Register (never unregister via Redis) an `asyncio.Queue` for `scan_run_id`.

        Cancellation-safe: deregistration in `finally` is a synchronous
        `set.discard`, never an `await`, so it runs correctly even when this
        context manager is torn down by `CancelledError`.
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_MAX_QUEUED_EVENTS)
        self._subscribers.setdefault(scan_run_id, set()).add(queue)
        try:
            yield queue
        finally:
            bucket = self._subscribers.get(scan_run_id)
            if bucket is not None:
                bucket.discard(queue)
                if not bucket:
                    del self._subscribers[scan_run_id]  # no unbounded key growth

    async def stop(self) -> None:
        """Cancel the reader, `punsubscribe`, and close both the `PubSub` and
        the client. Safe to call even when `start()` was a no-op."""
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._pubsub is not None:
            await self._pubsub.punsubscribe()
            await self._pubsub.aclose()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
