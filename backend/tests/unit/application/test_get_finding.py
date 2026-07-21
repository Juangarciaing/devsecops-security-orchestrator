"""`get_finding` use case — single redacted finding by id. Powers `GET /findings/{id}`."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_finding import FindingNotFoundError, get_finding
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.finding_port import FindingDiffSets, FindingPort, FindingTrendBucket
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

    def seed(self, finding: Finding) -> None:
        self._by_id[finding.id] = finding

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        return self._by_id.get(finding_id)

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        return []  # pragma: no cover — unused in these tests

    async def create(self, finding: Finding) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

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

    async def trend_counts_by_first_seen_run(
        self,
        repository_id: uuid.UUID,
        *,
        scanner_type: ScannerType | None = None,
        date_from: object = None,
        date_to: object = None,
        limit: int = 100,
    ) -> list[FindingTrendBucket]:
        return []  # pragma: no cover — unused in these tests

    async def open_counts_by_severity(self, repository_id: uuid.UUID) -> dict[FindingSeverity, int]:
        return {}  # pragma: no cover — unused in these tests

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

    async def diff_between_runs(
        self, repository_id: uuid.UUID, latest_run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> FindingDiffSets:
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
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY='AKIA...'",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_get_finding_raises_not_found_for_absent_finding() -> None:
    finding_port = _FakeFindingRepository()

    with pytest.raises(FindingNotFoundError):
        asyncio.run(get_finding(finding_port, uuid.uuid4(), UserRole.ADMIN))


def test_get_finding_returns_the_matching_finding() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)

    result = asyncio.run(get_finding(finding_port, finding.id, UserRole.ADMIN))

    assert result.id == finding.id


def test_get_finding_redacts_sensitive_fields_for_member() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)

    result = asyncio.run(get_finding(finding_port, finding.id, UserRole.MEMBER))

    assert result.raw_evidence is None
    assert result.snippet is None
    assert result.file_path is None
    assert result.line_number is None


def test_get_finding_leaves_sensitive_fields_intact_for_admin() -> None:
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)

    result = asyncio.run(get_finding(finding_port, finding.id, UserRole.ADMIN))

    assert result.raw_evidence == finding.raw_evidence
    assert result.snippet == finding.snippet
    assert result.file_path == finding.file_path
    assert result.line_number == finding.line_number
