"""ScanRunRead/Create schema — round-trip and enum validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.scan_run import ScanRunRead
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.value_objects.enums import ScanRunStatus


def _make_entity(**overrides: object) -> ScanRun:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": uuid.uuid4(),
        "status": ScanRunStatus.PENDING,
        "trigger": "push",
        "commit_sha": "abc123",
        "ref": "refs/heads/main",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_all_fields() -> None:
    entity = _make_entity()

    schema = ScanRunRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity


def test_round_trip_preserves_all_fields_with_timestamps_set() -> None:
    now = datetime.now(UTC)
    entity = _make_entity(
        status=ScanRunStatus.COMPLETED,
        trigger="manual",
        commit_sha="def456",
        ref="refs/heads/develop",
        started_at=now,
        completed_at=now,
    )

    schema = ScanRunRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.status is ScanRunStatus.COMPLETED


def test_invalid_status_raises_validation_error() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        ScanRunRead(
            id=uuid.uuid4(),
            repository_id=uuid.uuid4(),
            status="in_progress",  # type: ignore[arg-type]
            trigger="push",
            commit_sha="abc123",
            ref="refs/heads/main",
            created_at=now,
            started_at=None,
            completed_at=None,
        )
