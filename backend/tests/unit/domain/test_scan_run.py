"""ScanRun entity — belongs to one CodeRepository, carries run-level status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.value_objects.enums import ScanRunStatus


def test_scan_run_belongs_to_one_repository() -> None:
    repository_id = uuid.uuid4()
    now = datetime.now(UTC)

    run = ScanRun(
        id=uuid.uuid4(),
        repository_id=repository_id,
        status=ScanRunStatus.PENDING,
        trigger="manual",
        commit_sha="abc123",
        ref="refs/heads/main",
        started_at=None,
        completed_at=None,
        created_at=now,
    )

    assert run.repository_id == repository_id


def test_scan_run_fields_are_stored_as_provided() -> None:
    now = datetime.now(UTC)
    started = datetime.now(UTC)
    completed = datetime.now(UTC)

    run = ScanRun(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        status=ScanRunStatus.RUNNING,
        trigger="webhook",
        commit_sha="deadbeef",
        ref="refs/heads/develop",
        started_at=started,
        completed_at=completed,
        created_at=now,
    )

    assert run.status is ScanRunStatus.RUNNING
    assert run.trigger == "webhook"
    assert run.commit_sha == "deadbeef"
    assert run.ref == "refs/heads/develop"
    assert run.started_at == started
    assert run.completed_at == completed
    assert run.created_at == now


def test_scan_run_defaults_started_and_completed_to_none() -> None:
    now = datetime.now(UTC)

    run = ScanRun(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        status=ScanRunStatus.PENDING,
        trigger="manual",
        commit_sha="abc123",
        ref="refs/heads/main",
        created_at=now,
    )

    assert run.started_at is None
    assert run.completed_at is None
