"""Live-Redis leak-proof integration test (task 1.29; design D-PubSub /
Threat Matrix "Resource exhaustion — Redis subscriptions").

Requires a reachable Redis at `redis://localhost:6379/0` — published by
`docker-compose.override.yml`'s `redis.ports` mapping (mirrors the existing
`postgres` host-publish precedent); bring it up with
`docker compose up -d redis` if it is not already running.

This exercises the REAL `ScanEventRelay` against a REAL Redis instance —
`ScanEventRelay.start()` issues an actual `PSUBSCRIBE scan:*:events` over a
real `redis.asyncio` connection, and a second, independent sync `redis`
client queries `PUBSUB NUMPAT`/`PUBSUB CHANNELS` from outside to observe the
server-side subscription state.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
import redis as sync_redis

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.realtime.relay import ScanEventRelay

pytestmark = pytest.mark.integration

_LIVE_REDIS_URL = "redis://localhost:6379/0"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url=_LIVE_REDIS_URL,
        secret_key="s",
        jwt_secret_key="j",
        realtime_enabled=True,
    )


def _numpat() -> int:
    """Number of active PATTERN subscriptions server-wide — the relay's
    `PSUBSCRIBE scan:*:events` is the only one this test expects to exist."""
    client = sync_redis.Redis.from_url(_LIVE_REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
    try:
        return int(client.pubsub_numpat())
    finally:
        client.close()


def _channels() -> list[bytes]:
    """Exact (non-pattern) subscriptions — must stay empty: the relay only
    ever `PSUBSCRIBE`s, never plain `SUBSCRIBE`s."""
    client = sync_redis.Redis.from_url(_LIVE_REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
    try:
        return list(client.pubsub_channels())
    finally:
        client.close()


def test_psubscribe_count_stays_at_one_regardless_of_concurrent_client_count() -> None:
    """The resource-exhaustion leak proof: exactly ONE Redis pattern
    subscription for the relay's whole process lifetime — unaffected by 0,
    10 concurrent, or 0-again in-process SSE client registrations — and a
    clean `PUNSUBSCRIBE` when the relay itself stops."""
    assert _numpat() == 0, (
        "a stray PSUBSCRIBE from a previous run/process is polluting this test — "
        "check for a leaked relay/connection before re-running"
    )

    async def _run() -> tuple[int, int, int, int]:
        relay = ScanEventRelay(_settings())
        await relay.start()
        try:
            numpat_with_zero_clients = _numpat()

            async with contextlib.AsyncExitStack() as stack:
                for i in range(10):
                    await stack.enter_async_context(relay.subscribe(f"concurrent-scan-{i}"))
                numpat_with_ten_concurrent_clients = _numpat()

            # every `async with` above has now exited — all 10 "SSE clients" disconnected
            numpat_after_all_disconnect = _numpat()
        finally:
            await relay.stop()

        numpat_after_relay_stop = _numpat()
        return (
            numpat_with_zero_clients,
            numpat_with_ten_concurrent_clients,
            numpat_after_all_disconnect,
            numpat_after_relay_stop,
        )

    (
        numpat_with_zero_clients,
        numpat_with_ten_concurrent_clients,
        numpat_after_all_disconnect,
        numpat_after_relay_stop,
    ) = asyncio.run(_run())

    assert numpat_with_zero_clients == 1
    assert numpat_with_ten_concurrent_clients == 1
    assert numpat_after_all_disconnect == 1
    assert numpat_after_relay_stop == 0
    assert _channels() == []  # never a plain SUBSCRIBE, only PSUBSCRIBE, throughout


def test_worker_sync_publish_reaches_the_api_async_relay_across_processes() -> None:
    """Task 2.7 (realtime-push PR2, design's Data Flow diagram): the
    worker-side SYNC `publish_scan_status` (its own independently-constructed
    `redis.Redis` client, built lazily inside `publisher.py` — the same shape
    a forked Celery child uses) actually reaches the API-side ASYNC
    `ScanEventRelay` (its own independently-constructed `redis.asyncio.Redis`
    client) over the real `scan:{id}:events` channel naming — the two halves
    of this feature never share a client, a connection, or even an event
    loop, and this is the one test that proves they still talk to each other
    correctly through Redis."""
    from orchestrator.domain.value_objects.enums import ScanRunStatus
    from orchestrator.infrastructure.realtime.events import ScanStatusEvent
    from orchestrator.infrastructure.realtime.publisher import publish_scan_status

    scan_run_id = uuid.uuid4()

    async def _run() -> str:
        relay = ScanEventRelay(_settings())
        await relay.start()
        try:
            async with relay.subscribe(str(scan_run_id)) as queue:
                # Worker-side half: sync, blocking, its own real Redis client —
                # exactly how `process_scan_task`'s sync body calls it (PR2).
                publish_scan_status(scan_run_id, ScanRunStatus.RUNNING, settings=_settings())
                return await asyncio.wait_for(queue.get(), timeout=5.0)
        finally:
            await relay.stop()

    raw_payload = asyncio.run(_run())

    event = ScanStatusEvent.from_json(raw_payload)
    assert event.scan_run_id == scan_run_id
    assert event.status == ScanRunStatus.RUNNING
