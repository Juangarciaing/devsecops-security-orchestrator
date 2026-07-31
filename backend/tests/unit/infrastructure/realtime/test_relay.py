"""`ScanEventRelay` — one process-wide `psubscribe`, in-process fan-out
(design D-PubSub). A hand-rolled fake `PubSub`/`Redis` avoids a new test
dependency (no `fakeredis`)."""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.infrastructure.realtime.relay import ScanEventRelay


class _FakePubSub:
    def __init__(self) -> None:
        self.psubscribe_calls = 0
        self.punsubscribe_calls = 0
        self.closed = False
        self._queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()

    async def psubscribe(self, _pattern: str) -> None:
        self.psubscribe_calls += 1

    async def punsubscribe(self) -> None:
        self.punsubscribe_calls += 1

    async def aclose(self) -> None:
        self.closed = True

    async def get_message(self, timeout: float = 1.0) -> dict[str, str] | None:  # noqa: ARG002
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.05)
        except TimeoutError:
            return None

    def push(self, channel: str, data: str) -> None:
        self._queue.put_nowait({"type": "pmessage", "channel": channel, "data": data})


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub
        self.aclose_called = False

    def pubsub(self, ignore_subscribe_messages: bool = True) -> _FakePubSub:  # noqa: ARG002
        return self._pubsub

    async def aclose(self) -> None:
        self.aclose_called = True


async def _running_relay(fake_pubsub: _FakePubSub) -> ScanEventRelay:
    relay = ScanEventRelay(redis_client_factory=lambda: _FakeRedis(fake_pubsub))
    await relay.start()
    return relay


def test_start_issues_exactly_one_psubscribe(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> None:
        relay = await _running_relay(fake_pubsub)
        await relay.stop()

    asyncio.run(_run())

    assert fake_pubsub.psubscribe_calls == 1


def test_start_issues_one_psubscribe_regardless_of_subscriber_count() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> None:
        relay = await _running_relay(fake_pubsub)
        async with relay.subscribe("a"), relay.subscribe("b"), relay.subscribe("c"):
            pass
        await relay.stop()

    asyncio.run(_run())

    assert fake_pubsub.psubscribe_calls == 1


def test_fan_out_delivers_to_multiple_queues_for_the_same_scan() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> tuple[str, str]:
        relay = await _running_relay(fake_pubsub)
        async with relay.subscribe("scan-1") as q1, relay.subscribe("scan-1") as q2:
            fake_pubsub.push("scan:scan-1:events", "payload")
            msg1 = await asyncio.wait_for(q1.get(), timeout=1.0)
            msg2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        await relay.stop()
        return msg1, msg2

    msg1, msg2 = asyncio.run(_run())

    assert msg1 == "payload"
    assert msg2 == "payload"


def test_unrelated_scan_channel_is_not_delivered() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> bool:
        relay = await _running_relay(fake_pubsub)
        async with relay.subscribe("scan-1") as queue:
            fake_pubsub.push("scan:other-scan:events", "payload")
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=0.2)
        await relay.stop()
        return True

    assert asyncio.run(_run())


def test_queue_removed_and_bucket_deleted_after_generator_cancellation() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> ScanEventRelay:
        relay = await _running_relay(fake_pubsub)

        async def _consume() -> None:
            async with relay.subscribe("scan-1"):
                await asyncio.sleep(10)

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return relay

    relay = asyncio.run(_run())

    assert relay._subscribers == {}


def test_full_queue_drops_without_blocking_the_reader() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> int:
        relay = await _running_relay(fake_pubsub)
        async with relay.subscribe("scan-1") as queue:
            for i in range(20):
                fake_pubsub.push("scan:scan-1:events", f"event-{i}")
            await asyncio.sleep(0.2)  # let the reader drain the fake pubsub
            size = queue.qsize()
        await relay.stop()
        return size

    size = asyncio.run(_run())

    assert size <= 16  # maxsize — never grows unbounded, reader never blocks


def test_stop_cancels_the_reader_and_closes_pubsub_and_client() -> None:
    fake_pubsub = _FakePubSub()

    async def _run() -> tuple[_FakePubSub, bool]:
        relay = await _running_relay(fake_pubsub)
        redis_client = relay._redis
        await relay.stop()
        return fake_pubsub, redis_client.aclose_called  # type: ignore[union-attr]

    pubsub, redis_aclose_called = asyncio.run(_run())

    assert pubsub.punsubscribe_calls == 1
    assert pubsub.closed is True
    assert redis_aclose_called is True
