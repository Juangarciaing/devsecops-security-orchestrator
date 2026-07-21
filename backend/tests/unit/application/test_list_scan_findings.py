"""`list_scan_findings` use case — paginated, redacted findings for one scan run.
Powers `GET /scans/{scan_run_id}/findings`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.list_scan_findings import (
    ScanRunNotFoundError,
    list_scan_findings,
)
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.finding_port import FindingDiffSets, FindingPort, FindingTrendBucket
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    ScannerType,
    ScanRunStatus,
    UserRole,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ScanRun] = {}

    def seed(self, run: ScanRun) -> None:
        self._by_id[run.id] = run

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        return self._by_id.get(scan_run_id)

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        return [r for r in self._by_id.values() if r.repository_id == repository_id]

    async def create(self, scan_run: ScanRun) -> ScanRun:
        self._by_id[scan_run.id] = scan_run
        return scan_run

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        run = self._by_id[scan_run_id]
        run.status = status
        return run

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        return list(self._by_id.values())[offset : offset + limit]

    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        raise NotImplementedError  # pragma: no cover — unused in these tests


class _FakeFindingRepository(FindingPort):
    def __init__(self) -> None:
        self._by_scan_run: dict[uuid.UUID, list[Finding]] = {}
        self.calls: list[tuple[uuid.UUID, int, int]] = []

    def seed(self, scan_run_id: uuid.UUID, findings: list[Finding]) -> None:
        self._by_scan_run.setdefault(scan_run_id, []).extend(findings)

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        for findings in self._by_scan_run.values():
            for f in findings:
                if f.id == finding_id:
                    return f
        return None

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        return []  # pragma: no cover — unused in these tests, only present to satisfy the ABC

    async def create(self, finding: Finding) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        return len(self._by_scan_run.get(scan_run_id, []))  # pragma: no cover — unused

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        self.calls.append((scan_run_id, limit, offset))
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
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def diff_between_runs(
        self, repository_id: uuid.UUID, latest_run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> FindingDiffSets:
        raise NotImplementedError  # pragma: no cover — unused in these tests


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
        "file_path": "src/config.py",
        "line_number": 42,
        "raw_evidence": {"match": "AKIA..."},
        "snippet": "API_KEY='AKIA...'",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_list_scan_findings_raises_not_found_for_absent_run() -> None:
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()

    with pytest.raises(ScanRunNotFoundError):
        asyncio.run(list_scan_findings(scan_run_port, finding_port, uuid.uuid4(), UserRole.ADMIN))


def test_list_scan_findings_returns_paginated_findings_for_the_run() -> None:
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()
    run = _make_run()
    scan_run_port.seed(run)
    findings = [_make_finding() for _ in range(3)]
    finding_port.seed(run.id, findings)

    result = asyncio.run(
        list_scan_findings(scan_run_port, finding_port, run.id, UserRole.ADMIN, limit=2, offset=0)
    )

    assert len(result) == 2
    assert finding_port.calls == [(run.id, 2, 0)]


def test_list_scan_findings_returns_empty_list_when_run_has_no_findings() -> None:
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()
    run = _make_run()
    scan_run_port.seed(run)

    result = asyncio.run(list_scan_findings(scan_run_port, finding_port, run.id, UserRole.ADMIN))

    assert result == []


def test_list_scan_findings_redacts_sensitive_fields_for_member() -> None:
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()
    run = _make_run()
    scan_run_port.seed(run)
    finding = _make_finding()
    finding_port.seed(run.id, [finding])

    result = asyncio.run(list_scan_findings(scan_run_port, finding_port, run.id, UserRole.MEMBER))

    assert result[0].raw_evidence is None
    assert result[0].snippet is None
    assert result[0].file_path is None
    assert result[0].line_number is None


def test_list_scan_findings_leaves_sensitive_fields_intact_for_admin() -> None:
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()
    run = _make_run()
    scan_run_port.seed(run)
    finding = _make_finding()
    finding_port.seed(run.id, [finding])

    result = asyncio.run(list_scan_findings(scan_run_port, finding_port, run.id, UserRole.ADMIN))

    assert result[0].raw_evidence == finding.raw_evidence
    assert result[0].snippet == finding.snippet
    assert result[0].file_path == finding.file_path
    assert result[0].line_number == finding.line_number
