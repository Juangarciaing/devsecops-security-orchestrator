"""`ScanTriggerRequest`/`ScanRunDetailRead` schemas — request validation and
run+task+findings-count composition (spec: `GET /scans/{id}` returns a
findings COUNT, never a findings list)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.scan_trigger import ScanRunDetailRead, ScanTriggerRequest
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus


def _make_run(**overrides: object) -> ScanRun:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": uuid.uuid4(),
        "status": ScanRunStatus.PENDING,
        "trigger": "manual",
        "commit_sha": "abc123",
        "ref": "abc123",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


def _make_task(**overrides: object) -> ScanTask:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_run_id": uuid.uuid4(),
        "scanner_type": ScannerType.SECRETS,
        "status": ScanTaskStatus.PENDING,
        "started_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults.update(overrides)
    return ScanTask(**defaults)  # type: ignore[arg-type]


def test_scan_trigger_request_defaults_are_optional() -> None:
    request = ScanTriggerRequest()

    assert request.commit_sha is None
    assert request.scanner_type is None


def test_scan_trigger_request_accepts_explicit_values() -> None:
    request = ScanTriggerRequest(commit_sha="deadbeef", scanner_type=ScannerType.SAST)

    assert request.commit_sha == "deadbeef"
    assert request.scanner_type is ScannerType.SAST


def test_scan_trigger_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ScanTriggerRequest(commit_sha="abc123", branch="main")  # type: ignore[call-arg]


def test_scan_run_detail_read_composes_run_task_and_findings_count() -> None:
    run = _make_run(status=ScanRunStatus.COMPLETED)
    task = _make_task(scan_run_id=run.id, status=ScanTaskStatus.COMPLETED)

    detail = ScanRunDetailRead.from_run_task_and_count(run, task, findings_count=1)

    assert detail.id == run.id
    assert detail.repository_id == run.repository_id
    assert detail.status is ScanRunStatus.COMPLETED
    assert detail.task_status is ScanTaskStatus.COMPLETED
    assert detail.findings_count == 1


def test_scan_run_detail_read_findings_count_can_be_zero() -> None:
    run = _make_run()
    task = _make_task(scan_run_id=run.id)

    detail = ScanRunDetailRead.from_run_task_and_count(run, task, findings_count=0)

    assert detail.findings_count == 0
