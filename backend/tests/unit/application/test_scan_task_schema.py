"""ScanTaskRead/Create schema — round-trip and enum validation."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.scan_task import ScanTaskRead
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus


def _make_entity(**overrides: object) -> ScanTask:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_run_id": uuid.uuid4(),
        "scanner_type": ScannerType.SAST,
        "status": ScanTaskStatus.PENDING,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults.update(overrides)
    return ScanTask(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_all_fields() -> None:
    entity = _make_entity()

    schema = ScanTaskRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity


def test_round_trip_preserves_error_message_on_failure() -> None:
    entity = _make_entity(
        scanner_type=ScannerType.SECRETS,
        status=ScanTaskStatus.FAILED,
        error_message="scanner crashed with exit code 1",
    )

    schema = ScanTaskRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.error_message == "scanner crashed with exit code 1"


def test_invalid_scanner_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        ScanTaskRead(
            id=uuid.uuid4(),
            scan_run_id=uuid.uuid4(),
            scanner_type="fuzz",  # type: ignore[arg-type]
            status=ScanTaskStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_message=None,
        )
