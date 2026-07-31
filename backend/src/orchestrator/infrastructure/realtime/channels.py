"""`scan:{scan_run_id}:events` channel naming — the one place that knows it.

The relay `psubscribe`s `SCAN_EVENTS_PATTERN` once at startup (design
D-PubSub); `scan_run_id_from_channel` recovers the id from an inbound
pattern-subscribe message so the relay can fan out to the right queues.
"""

from __future__ import annotations

import uuid

SCAN_EVENTS_PATTERN = "scan:*:events"

_PREFIX = "scan:"
_SUFFIX = ":events"


def scan_events_channel(scan_run_id: uuid.UUID | str) -> str:
    """Build the Redis channel name for `scan_run_id`."""
    return f"{_PREFIX}{scan_run_id}{_SUFFIX}"


def scan_run_id_from_channel(channel: str) -> str:
    """Recover the `scan_run_id` string from a channel built by `scan_events_channel`."""
    return channel[len(_PREFIX) : -len(_SUFFIX)]
