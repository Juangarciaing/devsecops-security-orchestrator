"""FindingRead/Create schema — round-trip preserving redaction-sensitive fields
and enum validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.finding import FindingRead
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus


def _make_entity(**overrides: object) -> Finding:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": uuid.uuid4(),
        "severity": FindingSeverity.HIGH,
        "rule_id": "RULE-001",
        "title": "Hardcoded secret",
        "fingerprint": "abc123fingerprint",
        "created_at": now,
        "updated_at": now,
        "status": FindingStatus.OPEN,
        "description": None,
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY = 'AKIA...'",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_status_and_redaction_sensitive_fields() -> None:
    entity = _make_entity()

    schema = FindingRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert round_tripped.status == FindingStatus.OPEN
    assert round_tripped.raw_evidence == entity.raw_evidence
    assert round_tripped.snippet == entity.snippet
    assert round_tripped.file_path == entity.file_path
    assert round_tripped.line_number == entity.line_number


def test_round_trip_preserves_non_default_status_and_evidence() -> None:
    entity = _make_entity(
        severity=FindingSeverity.CRITICAL,
        status=FindingStatus.SUPPRESSED,
        rule_id="RULE-002",
        title="SQL injection",
        fingerprint="def456fingerprint",
        description="Unsanitized user input reaches a raw SQL query.",
        file_path="src/db.py",
        line_number=17,
        raw_evidence={"query": "SELECT * FROM users WHERE id = ' + user_id"},
        snippet="cursor.execute(...)",
    )

    schema = FindingRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.status is FindingStatus.SUPPRESSED
    assert schema.severity is FindingSeverity.CRITICAL


def test_invalid_severity_raises_validation_error() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        FindingRead(
            id=uuid.uuid4(),
            scan_task_id=uuid.uuid4(),
            severity="urgent",  # type: ignore[arg-type]
            status=FindingStatus.OPEN,
            rule_id="RULE-001",
            title="Hardcoded secret",
            fingerprint="abc123fingerprint",
            created_at=now,
            updated_at=now,
            description=None,
            file_path=None,
            line_number=None,
            raw_evidence=None,
            snippet=None,
        )
