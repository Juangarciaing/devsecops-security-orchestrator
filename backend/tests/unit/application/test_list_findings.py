"""`list_findings` use case — cross-run filtered, redacted, paginated findings.
Powers `GET /findings`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.list_findings import list_findings
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
    def __init__(self, findings: list[Finding] | None = None) -> None:
        self._findings = findings or []
        self.calls: list[dict[str, object]] = []

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        return None  # pragma: no cover — unused in these tests

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
        self.calls.append(
            {
                "severity": severity,
                "status": status,
                "repository_id": repository_id,
                "scanner_type": scanner_type,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._findings[offset : offset + limit]

    async def diff_between_runs(
        self, repository_id: uuid.UUID, latest_run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> FindingDiffSets:
        return FindingDiffSets()  # pragma: no cover — unused in these tests


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


def test_list_findings_passes_all_filters_through_to_the_port() -> None:
    finding_port = _FakeFindingRepository()
    repository_id = uuid.uuid4()

    asyncio.run(
        list_findings(
            finding_port,
            UserRole.ADMIN,
            severity=FindingSeverity.CRITICAL,
            status=FindingStatus.OPEN,
            repository_id=repository_id,
            scanner_type=ScannerType.SECRETS,
            limit=10,
            offset=5,
        )
    )

    assert finding_port.calls == [
        {
            "severity": FindingSeverity.CRITICAL,
            "status": FindingStatus.OPEN,
            "repository_id": repository_id,
            "scanner_type": ScannerType.SECRETS,
            "limit": 10,
            "offset": 5,
        }
    ]


def test_list_findings_returns_empty_list_when_nothing_matches() -> None:
    finding_port = _FakeFindingRepository(findings=[])

    result = asyncio.run(list_findings(finding_port, UserRole.ADMIN))

    assert result == []


def test_list_findings_redacts_sensitive_fields_for_member() -> None:
    finding = _make_finding()
    finding_port = _FakeFindingRepository(findings=[finding])

    result = asyncio.run(list_findings(finding_port, UserRole.MEMBER))

    assert result[0].raw_evidence is None
    assert result[0].snippet is None
    assert result[0].file_path is None
    assert result[0].line_number is None


def test_list_findings_leaves_sensitive_fields_intact_for_admin() -> None:
    finding = _make_finding()
    finding_port = _FakeFindingRepository(findings=[finding])

    result = asyncio.run(list_findings(finding_port, UserRole.ADMIN))

    assert result[0].raw_evidence == finding.raw_evidence
    assert result[0].snippet == finding.snippet
    assert result[0].file_path == finding.file_path
    assert result[0].line_number == finding.line_number
