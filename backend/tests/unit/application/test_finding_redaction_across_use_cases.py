"""Module 8 PR2 task 2.6 — a single consolidated check that EVERY findings use
case masks exactly the 4 `Finding.REDACTION_SENSITIVE_FIELDS`
(`raw_evidence`, `snippet`, `file_path`, `line_number`) for a member caller,
and leaves them intact for an admin caller. Individual use-case test files
also cover this locally; this file proves the guarantee holds uniformly
across all 5 endpoints in one place.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.use_cases.get_finding import get_finding
from orchestrator.application.use_cases.list_findings import list_findings
from orchestrator.application.use_cases.list_scan_findings import list_scan_findings
from orchestrator.application.use_cases.suppress_finding import suppress_finding
from orchestrator.application.use_cases.unsuppress_finding import unsuppress_finding
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.finding_port import FindingPort, FindingTrendBucket
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    ScannerType,
    ScanRunStatus,
    UserRole,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)

_SENSITIVE_FIELDS = ("raw_evidence", "snippet", "file_path", "line_number")


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ScanRun] = {}

    def seed(self, run: ScanRun) -> None:
        self._by_id[run.id] = run

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        return self._by_id.get(scan_run_id)

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        return []  # pragma: no cover — unused

    async def create(self, scan_run: ScanRun) -> ScanRun:
        raise NotImplementedError  # pragma: no cover — unused

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        raise NotImplementedError  # pragma: no cover — unused

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        return []  # pragma: no cover — unused


class _FakeFindingRepository(FindingPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Finding] = {}
        self._by_scan_run: dict[uuid.UUID, list[Finding]] = {}

    def seed(self, finding: Finding, *, scan_run_id: uuid.UUID | None = None) -> None:
        self._by_id[finding.id] = finding
        if scan_run_id is not None:
            self._by_scan_run.setdefault(scan_run_id, []).append(finding)

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        return self._by_id.get(finding_id)

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        return []  # pragma: no cover — unused

    async def create(self, finding: Finding) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        finding = self._by_id[finding_id]
        finding.status = status
        finding.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return finding

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        raise NotImplementedError  # pragma: no cover — unused

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        return 0  # pragma: no cover — unused

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        return self._by_scan_run.get(scan_run_id, [])[offset : offset + limit]

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
        return list(self._by_id.values())[offset : offset + limit]


def _make_run(**overrides: object) -> ScanRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": uuid.uuid4(),
        "status": ScanRunStatus.COMPLETED,
        "trigger": "manual",
        "commit_sha": "abc123",
        "ref": "abc123",
        "created_at": _NOW,
        "started_at": _NOW,
        "completed_at": _NOW,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


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


def _assert_masked(result: FindingRead) -> None:
    for field_name in _SENSITIVE_FIELDS:
        assert getattr(result, field_name) is None, f"{field_name} not masked for member"


def _assert_untouched(result: FindingRead, original: Finding) -> None:
    for field_name in _SENSITIVE_FIELDS:
        assert getattr(result, field_name) == getattr(original, field_name), (
            f"{field_name} unexpectedly changed for admin"
        )


def test_every_finding_use_case_masks_exactly_the_four_sensitive_fields_for_member() -> None:
    scan_run_port = _FakeScanRunRepository()
    run = _make_run()
    scan_run_port.seed(run)

    # list_scan_findings
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding, scan_run_id=run.id)
    [result] = asyncio.run(list_scan_findings(scan_run_port, finding_port, run.id, UserRole.MEMBER))
    _assert_masked(result)

    # list_findings
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)
    [result] = asyncio.run(list_findings(finding_port, UserRole.MEMBER))
    _assert_masked(result)

    # get_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)
    result = asyncio.run(get_finding(finding_port, finding.id, UserRole.MEMBER))
    _assert_masked(result)

    # suppress_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.OPEN)
    finding_port.seed(finding)
    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.MEMBER))
    _assert_masked(result)

    # unsuppress_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.SUPPRESSED)
    finding_port.seed(finding)
    result = asyncio.run(unsuppress_finding(finding_port, finding.id, UserRole.MEMBER))
    _assert_masked(result)


def test_every_finding_use_case_leaves_sensitive_fields_intact_for_admin() -> None:
    scan_run_port = _FakeScanRunRepository()
    run = _make_run()
    scan_run_port.seed(run)

    # list_scan_findings
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding, scan_run_id=run.id)
    [result] = asyncio.run(list_scan_findings(scan_run_port, finding_port, run.id, UserRole.ADMIN))
    _assert_untouched(result, finding)

    # list_findings
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)
    [result] = asyncio.run(list_findings(finding_port, UserRole.ADMIN))
    _assert_untouched(result, finding)

    # get_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding()
    finding_port.seed(finding)
    result = asyncio.run(get_finding(finding_port, finding.id, UserRole.ADMIN))
    _assert_untouched(result, finding)

    # suppress_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.OPEN)
    finding_port.seed(finding)
    original_evidence = finding.raw_evidence
    original_snippet, original_path, original_line = (
        finding.snippet,
        finding.file_path,
        finding.line_number,
    )
    result = asyncio.run(suppress_finding(finding_port, finding.id, UserRole.ADMIN))
    assert result.raw_evidence == original_evidence
    assert result.snippet == original_snippet
    assert result.file_path == original_path
    assert result.line_number == original_line

    # unsuppress_finding
    finding_port = _FakeFindingRepository()
    finding = _make_finding(status=FindingStatus.SUPPRESSED)
    finding_port.seed(finding)
    original_evidence = finding.raw_evidence
    original_snippet, original_path, original_line = (
        finding.snippet,
        finding.file_path,
        finding.line_number,
    )
    result = asyncio.run(unsuppress_finding(finding_port, finding.id, UserRole.ADMIN))
    assert result.raw_evidence == original_evidence
    assert result.snippet == original_snippet
    assert result.file_path == original_path
    assert result.line_number == original_line
