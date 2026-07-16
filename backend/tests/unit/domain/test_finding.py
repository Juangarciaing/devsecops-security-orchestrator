"""Finding entity — status defaults to open; exposes REDACTION_SENSITIVE_FIELDS."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus


def _make_finding(**overrides: object) -> Finding:
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
        "description": None,
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY = 'AKIA...'",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_status_defaults_to_open_when_not_specified() -> None:
    finding = _make_finding()

    assert finding.status == FindingStatus.OPEN


def test_status_can_be_explicitly_overridden() -> None:
    finding = _make_finding(status=FindingStatus.RESOLVED)

    assert finding.status == FindingStatus.RESOLVED


def test_redaction_sensitive_fields_constant() -> None:
    assert Finding.REDACTION_SENSITIVE_FIELDS == frozenset(
        {"raw_evidence", "snippet", "file_path", "line_number"}
    )


def test_fields_are_stored_as_provided() -> None:
    now = datetime.now(UTC)

    finding = _make_finding(
        severity=FindingSeverity.CRITICAL,
        rule_id="RULE-002",
        title="SQL injection",
        fingerprint="def456fingerprint",
        created_at=now,
        updated_at=now,
        description="Unsanitized user input reaches a raw SQL query.",
        file_path="src/db.py",
        line_number=17,
        raw_evidence={"query": "SELECT * FROM users WHERE id = ' + user_id"},
        snippet="cursor.execute('SELECT * FROM users WHERE id = ' + user_id)",
    )

    assert finding.severity is FindingSeverity.CRITICAL
    assert finding.rule_id == "RULE-002"
    assert finding.title == "SQL injection"
    assert finding.fingerprint == "def456fingerprint"
    assert finding.created_at == now
    assert finding.updated_at == now
    assert finding.description == "Unsanitized user input reaches a raw SQL query."
    assert finding.file_path == "src/db.py"
    assert finding.line_number == 17
    assert finding.raw_evidence == {"query": "SELECT * FROM users WHERE id = ' + user_id"}
    assert finding.snippet == "cursor.execute('SELECT * FROM users WHERE id = ' + user_id)"
