"""`redact_finding_for_role` (D8) — pure `FindingRead -> FindingRead` masking.

Masks exactly `Finding.REDACTION_SENSITIVE_FIELDS` (`raw_evidence`, `snippet`,
`file_path`, `line_number`) to `None` for non-admin roles; admin sees the
finding untouched. No HTTP/DB dependency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus, UserRole


def _make_finding_read(**overrides: object) -> FindingRead:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": uuid.uuid4(),
        "severity": FindingSeverity.HIGH,
        "status": FindingStatus.OPEN,
        "rule_id": "RULE-001",
        "title": "Hardcoded secret",
        "fingerprint": "abc123fingerprint",
        "created_at": now,
        "updated_at": now,
        "description": "A secret was hardcoded.",
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY = 'AKIA...'",
    }
    defaults.update(overrides)
    return FindingRead(**defaults)  # type: ignore[arg-type]


def test_redact_finding_for_member_masks_exactly_the_four_sensitive_fields() -> None:
    finding = _make_finding_read()

    redacted = redact_finding_for_role(finding, UserRole.MEMBER)

    assert redacted.raw_evidence is None
    assert redacted.snippet is None
    assert redacted.file_path is None
    assert redacted.line_number is None


def test_redact_finding_for_member_leaves_non_sensitive_fields_intact() -> None:
    finding = _make_finding_read()

    redacted = redact_finding_for_role(finding, UserRole.MEMBER)

    assert redacted.id == finding.id
    assert redacted.scan_task_id == finding.scan_task_id
    assert redacted.severity == finding.severity
    assert redacted.status == finding.status
    assert redacted.rule_id == finding.rule_id
    assert redacted.title == finding.title
    assert redacted.fingerprint == finding.fingerprint
    assert redacted.description == finding.description


def test_redact_finding_for_admin_returns_the_finding_untouched() -> None:
    finding = _make_finding_read()

    redacted = redact_finding_for_role(finding, UserRole.ADMIN)

    assert redacted == finding
    assert redacted.raw_evidence == finding.raw_evidence
    assert redacted.snippet == finding.snippet
    assert redacted.file_path == finding.file_path
    assert redacted.line_number == finding.line_number


def test_redact_finding_for_member_is_a_no_op_when_sensitive_fields_already_none() -> None:
    finding = _make_finding_read(file_path=None, line_number=None, raw_evidence=None, snippet=None)

    redacted = redact_finding_for_role(finding, UserRole.MEMBER)

    assert redacted.raw_evidence is None
    assert redacted.snippet is None
    assert redacted.file_path is None
    assert redacted.line_number is None
