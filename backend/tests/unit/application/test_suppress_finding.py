"""`suppress_finding` use case — transitions a `Finding` to `SUPPRESSED` via the
`domain.services.finding_transitions` FSM. Powers `POST /findings/{id}/suppress`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_finding import FindingNotFoundError
from orchestrator.application.use_cases.suppress_finding import suppress_finding
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.services.finding_transitions import IllegalStatusTransitionError
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    ScannerType,
    UserRole,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeFindingRepository(FindingPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Finding] = {}
        self.update_status_calls: list[tuple[uuid.UUID, FindingStatus]] = []

    def seed(self, finding: Finding) -> None:
        self._by_id[finding.id] = finding

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        return self._by_id.get(finding_id)

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        return []  # pragma: no cover — unused in these tests

    async def create(self, finding: Finding) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        self.update_status_calls.append((finding_id, status))
        finding = self._by_id[finding_id]
        finding.status = status
        finding.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return finding

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        return 0  # pragma: no cover — unused in these tests

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        return []  # pragma: no cover — unused in these tests

    async def list_findings(
        self,
        *,
        severity: FindingSeverity | None = None,
        status: FindingStatus | None = None,
        repository_id: uuid.UUID | None = None,
        scanner_type: ScannerType | None = None,
        limit: int,
        offset: int,
    ) -> list[Finding]:
        raise NotImplementedError  # pragma: no cover — unused in these tests


def _make_finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_task_id": uuid.uuid4(),
        "severity": FindingSeverity.HIGH,
        "rule_id": "rule",
        "title": "title",
        "fingerprint": f"fp-{uuid.uuid4()}",
        "created_at": _NOW,
        "updated_at": _NOW,
        "status": FindingStatus.OPEN,
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY='AKIA...'",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_suppress_finding_raises_not_found_for_absent_finding() -> None:
    finding_port = _FakeFindingRepository()

    with pytest.raises(FindingNotFoundError):
        asyncio.run(suppress_finding(finding_port, uuid.uuid4(), UserRole.ADMIN))


def test_suppress_finding_transitions_open_to_suppressed_and_writes() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.OPEN)
    finding_port.seed(finding)

    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.ADMIN))

    assert result.status == FindingStatus.SUPPRESSED
    assert finding_port.update_status_calls == [(finding.id, FindingStatus.SUPPRESSED)]


def test_suppress_finding_already_suppressed_is_idempotent_no_write() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.SUPPRESSED)
    finding_port.seed(finding)

    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.ADMIN))

    assert result.status == FindingStatus.SUPPRESSED
    assert finding_port.update_status_calls == []


@pytest.mark.parametrize("status", [FindingStatus.RESOLVED, FindingStatus.FALSE_POSITIVE])
def test_suppress_finding_raises_illegal_transition_for_resolved_or_false_positive(
    status: FindingStatus,
) -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=status)
    finding_port.seed(finding)

    with pytest.raises(IllegalStatusTransitionError):
        asyncio.run(suppress_finding(finding_port, finding.id, UserRole.ADMIN))

    assert finding_port.update_status_calls == []


def test_suppress_finding_redacts_sensitive_fields_for_member() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.OPEN)
    finding_port.seed(finding)

    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.MEMBER))

    assert result.raw_evidence is None
    assert result.snippet is None
    assert result.file_path is None
    assert result.line_number is None


def test_suppress_finding_leaves_sensitive_fields_intact_for_admin() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.OPEN)
    finding_port.seed(finding)
    original_evidence = finding.raw_evidence

    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.ADMIN))

    assert result.raw_evidence == original_evidence
    assert result.snippet == "API_KEY='AKIA...'"
    assert result.file_path == "src/config.py"
    assert result.line_number == 42
