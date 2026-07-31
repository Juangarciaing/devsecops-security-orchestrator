"""`channels.py` — the single place that knows the `scan:{id}:events` naming."""

from __future__ import annotations

import uuid

from orchestrator.infrastructure.realtime.channels import (
    SCAN_EVENTS_PATTERN,
    scan_events_channel,
    scan_run_id_from_channel,
)


def test_scan_events_channel_builds_expected_name() -> None:
    scan_run_id = uuid.uuid4()

    assert scan_events_channel(scan_run_id) == f"scan:{scan_run_id}:events"


def test_scan_events_channel_accepts_a_str_id() -> None:
    scan_run_id = str(uuid.uuid4())

    assert scan_events_channel(scan_run_id) == f"scan:{scan_run_id}:events"


def test_scan_run_id_from_channel_round_trips_with_scan_events_channel() -> None:
    scan_run_id = uuid.uuid4()
    channel = scan_events_channel(scan_run_id)

    assert scan_run_id_from_channel(channel) == str(scan_run_id)


def test_scan_events_pattern_matches_channel_shape() -> None:
    assert SCAN_EVENTS_PATTERN == "scan:*:events"
