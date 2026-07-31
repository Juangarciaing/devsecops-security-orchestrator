"""`ScanStatusEvent` — the sole wire contract published on Redis and framed as SSE data."""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.infrastructure.realtime.events import ScanStatusEvent


def test_to_json_round_trips_through_from_json() -> None:
    event = ScanStatusEvent(
        scan_run_id=uuid.uuid4(), status=ScanRunStatus.RUNNING, at="2026-07-31T15:04:05Z"
    )

    restored = ScanStatusEvent.from_json(event.to_json())

    assert restored == event


def test_to_json_produces_the_documented_field_shape() -> None:
    scan_run_id = uuid.uuid4()
    event = ScanStatusEvent(scan_run_id=scan_run_id, status=ScanRunStatus.COMPLETED, at="t")

    payload = json.loads(event.to_json())

    assert payload == {"scan_run_id": str(scan_run_id), "status": "completed", "at": "t"}


def test_to_json_escapes_newlines_so_a_payload_cannot_forge_an_sse_frame() -> None:
    """Threat matrix — response-splitting: a crafted `\\n\\nevent: ...` string
    fed through the encoder must never survive as literal newlines in the
    emitted JSON, so it cannot break out of the `data: ...` line."""
    scan_run_id = uuid.uuid4()
    event = ScanStatusEvent(scan_run_id=scan_run_id, status=ScanRunStatus.FAILED, at="t")

    raw = event.to_json()

    assert "\n" not in raw
    # even if an attacker controlled `at`, json.dumps escapes it
    injected = ScanStatusEvent(
        scan_run_id=scan_run_id, status=ScanRunStatus.FAILED, at="\n\nevent: evil\ndata: x"
    )
    assert "\n" not in injected.to_json()
