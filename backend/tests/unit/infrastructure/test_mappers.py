"""Entity <-> ORM model round-trip tests for all 4 aggregates.

Uses in-memory objects only (plain instantiation, no DB session/connection) —
verifies `to_model`/`to_entity` preserve every field.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.db.mappers import (
    code_repository_to_entity,
    code_repository_to_model,
    finding_to_entity,
    finding_to_model,
    scan_run_to_entity,
    scan_run_to_model,
    scan_task_to_entity,
    scan_task_to_model,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_code_repository_round_trip() -> None:
    entity = CodeRepository(
        id=uuid.uuid4(),
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = code_repository_to_model(entity)
    round_tripped = code_repository_to_entity(model)

    assert round_tripped == entity


def test_scan_run_round_trip() -> None:
    entity = ScanRun(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        status=ScanRunStatus.RUNNING,
        trigger="push",
        commit_sha="abc123",
        ref="refs/heads/main",
        created_at=_NOW,
        started_at=_NOW,
        completed_at=None,
    )

    model = scan_run_to_model(entity)
    round_tripped = scan_run_to_entity(model)

    assert round_tripped == entity


def test_scan_task_round_trip() -> None:
    entity = ScanTask(
        id=uuid.uuid4(),
        scan_run_id=uuid.uuid4(),
        scanner_type=ScannerType.SAST,
        status=ScanTaskStatus.FAILED,
        started_at=_NOW,
        completed_at=_NOW,
        error_message="boom",
    )

    model = scan_task_to_model(entity)
    round_tripped = scan_task_to_entity(model)

    assert round_tripped == entity


def test_finding_round_trip() -> None:
    entity = Finding(
        id=uuid.uuid4(),
        scan_task_id=uuid.uuid4(),
        severity=FindingSeverity.CRITICAL,
        rule_id="rule-1",
        title="Hardcoded secret",
        fingerprint="fp-1",
        created_at=_NOW,
        updated_at=_NOW,
        status=FindingStatus.SUPPRESSED,
        description="A secret was hardcoded",
        file_path="src/app.py",
        line_number=42,
        raw_evidence={"match": "AKIA..."},
        snippet="API_KEY = 'AKIA...'",
    )

    model = finding_to_model(entity)
    round_tripped = finding_to_entity(model)

    assert round_tripped == entity
