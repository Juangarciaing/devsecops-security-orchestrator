"""ScanTask entity — belongs to one ScanRun, one task per scanner type per run."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus


def _make_task(**overrides: object) -> ScanTask:
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


def test_scan_task_belongs_to_one_scan_run() -> None:
    scan_run_id = uuid.uuid4()

    task = _make_task(scan_run_id=scan_run_id)

    assert task.scan_run_id == scan_run_id


def test_scan_task_fields_are_stored_as_provided() -> None:
    started = datetime.now(UTC)
    completed = datetime.now(UTC)

    task = _make_task(
        scanner_type=ScannerType.SECRETS,
        status=ScanTaskStatus.FAILED,
        started_at=started,
        completed_at=completed,
        error_message="scanner crashed",
    )

    assert task.scanner_type is ScannerType.SECRETS
    assert task.status is ScanTaskStatus.FAILED
    assert task.started_at == started
    assert task.completed_at == completed
    assert task.error_message == "scanner crashed"


def test_same_scan_run_and_scanner_type_is_duplicate_task() -> None:
    scan_run_id = uuid.uuid4()
    existing = _make_task(scan_run_id=scan_run_id, scanner_type=ScannerType.SECRETS)
    candidate = _make_task(scan_run_id=scan_run_id, scanner_type=ScannerType.SECRETS)

    assert existing.conflicts_with(candidate) is True


def test_different_scanner_type_same_run_is_not_duplicate() -> None:
    scan_run_id = uuid.uuid4()
    existing = _make_task(scan_run_id=scan_run_id, scanner_type=ScannerType.SECRETS)
    candidate = _make_task(scan_run_id=scan_run_id, scanner_type=ScannerType.SAST)

    assert existing.conflicts_with(candidate) is False


def test_same_scanner_type_different_run_is_not_duplicate() -> None:
    existing = _make_task(scan_run_id=uuid.uuid4(), scanner_type=ScannerType.SECRETS)
    candidate = _make_task(scan_run_id=uuid.uuid4(), scanner_type=ScannerType.SECRETS)

    assert existing.conflicts_with(candidate) is False
