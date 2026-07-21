"""`get_repository_diff` use case — repo-scoped, exact ADDED/RESOLVED/CARRIED
finding partition between the latest completed `ScanRun` and the run
immediately before it. Powers `GET /repositories/{id}/diff`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.get_repository_diff import get_repository_diff
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingDiffSets, FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    RepositoryProvider,
    ScanRunStatus,
    UserRole,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_ref": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


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


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self, repositories: list[CodeRepository]) -> None:
        self._by_id = {repo.id: repo for repo in repositories}

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        return self._by_id.get(repository_id)

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_all(self) -> list[CodeRepository]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_active(self) -> list[CodeRepository]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def create(self, repository: CodeRepository) -> CodeRepository:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update(self, repository: CodeRepository) -> CodeRepository:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self, recent_completed: list[ScanRun] | None = None) -> None:
        self._recent_completed = recent_completed or []
        self.list_recent_completed_calls: list[tuple[uuid.UUID, int]] = []

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def create(self, scan_run: ScanRun) -> ScanRun:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        self.list_recent_completed_calls.append((repository_id, limit))
        return self._recent_completed[:limit]


class _FakeFindingRepository(FindingPort):
    def __init__(self, diff_sets: FindingDiffSets | None = None) -> None:
        self._diff_sets = diff_sets or FindingDiffSets()
        self.diff_calls: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def create(self, finding: Finding) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, finding_id: uuid.UUID, status: object) -> Finding:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_findings(
        self,
        *,
        severity: object = None,
        status: object = None,
        repository_id: uuid.UUID | None = None,
        scanner_type: object = None,
        limit: int,
        offset: int,
    ) -> list[Finding]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def trend_counts_by_first_seen_run(
        self,
        repository_id: uuid.UUID,
        *,
        scanner_type: object = None,
        date_from: object = None,
        date_to: object = None,
        limit: int = 100,
    ) -> list[object]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def open_counts_by_severity(self, repository_id: uuid.UUID) -> dict[object, int]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def diff_between_runs(
        self, repository_id: uuid.UUID, latest_run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> FindingDiffSets:
        self.diff_calls.append((repository_id, latest_run_id, baseline_run_id))
        return self._diff_sets


def test_get_repository_diff_raises_not_found_for_missing_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository([])
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(
            get_repository_diff(
                repository_port, scan_run_port, finding_port, uuid.uuid4(), UserRole.ADMIN
            )
        )


def test_get_repository_diff_raises_not_found_for_inactive_repository() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository()
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(
            get_repository_diff(
                repository_port, scan_run_port, finding_port, repo.id, UserRole.ADMIN
            )
        )


def test_get_repository_diff_zero_completed_runs_returns_null_runs_and_empty_sets() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository(recent_completed=[])
    finding_port = _FakeFindingRepository()

    result = asyncio.run(
        get_repository_diff(repository_port, scan_run_port, finding_port, repo.id, UserRole.ADMIN)
    )

    assert result.latest_run is None
    assert result.baseline_run is None
    assert result.added == []
    assert result.resolved == []
    assert result.carried == []
    assert scan_run_port.list_recent_completed_calls == [(repo.id, 2)]
    assert finding_port.diff_calls == []


def test_get_repository_diff_one_completed_run_baseline_null_all_added() -> None:
    repo = _make_repository()
    sole_run = _make_run(repository_id=repo.id)
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository(recent_completed=[sole_run])
    findings = [_make_finding() for _ in range(3)]
    finding_port = _FakeFindingRepository(diff_sets=FindingDiffSets(added=findings))

    result = asyncio.run(
        get_repository_diff(repository_port, scan_run_port, finding_port, repo.id, UserRole.ADMIN)
    )

    assert result.baseline_run is None
    assert result.latest_run is not None
    assert result.latest_run.scan_run_id == sole_run.id
    assert {f.id for f in result.added} == {f.id for f in findings}
    assert result.resolved == []
    assert result.carried == []
    # diff_between_runs must be called with the sole run as latest — the
    # baseline id passed is a throwaway sentinel that never matches a real
    # ScanRun (RESOLVED/CARRIED are always empty here, by definition).
    [(called_repo_id, called_latest_id, _sentinel_baseline_id)] = finding_port.diff_calls
    assert called_repo_id == repo.id
    assert called_latest_id == sole_run.id


def test_get_repository_diff_two_completed_runs_assembles_full_diff() -> None:
    repo = _make_repository()
    latest_run = _make_run(repository_id=repo.id, commit_sha="latest-sha")
    baseline_run = _make_run(repository_id=repo.id, commit_sha="baseline-sha")
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository(recent_completed=[latest_run, baseline_run])
    added = [_make_finding()]
    resolved = [_make_finding()]
    carried = [_make_finding()]
    finding_port = _FakeFindingRepository(
        diff_sets=FindingDiffSets(added=added, resolved=resolved, carried=carried)
    )

    result = asyncio.run(
        get_repository_diff(repository_port, scan_run_port, finding_port, repo.id, UserRole.ADMIN)
    )

    assert result.latest_run is not None
    assert result.baseline_run is not None
    assert result.latest_run.scan_run_id == latest_run.id
    assert result.latest_run.commit_sha == "latest-sha"
    assert result.baseline_run.scan_run_id == baseline_run.id
    assert result.baseline_run.commit_sha == "baseline-sha"
    assert {f.id for f in result.added} == {f.id for f in added}
    assert {f.id for f in result.resolved} == {f.id for f in resolved}
    assert {f.id for f in result.carried} == {f.id for f in carried}
    assert finding_port.diff_calls == [(repo.id, latest_run.id, baseline_run.id)]


def test_get_repository_diff_redacts_sensitive_fields_for_member_in_every_set() -> None:
    repo = _make_repository()
    latest_run = _make_run(repository_id=repo.id)
    baseline_run = _make_run(repository_id=repo.id)
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository(recent_completed=[latest_run, baseline_run])
    added = [_make_finding()]
    resolved = [_make_finding()]
    carried = [_make_finding()]
    finding_port = _FakeFindingRepository(
        diff_sets=FindingDiffSets(added=added, resolved=resolved, carried=carried)
    )

    result = asyncio.run(
        get_repository_diff(repository_port, scan_run_port, finding_port, repo.id, UserRole.MEMBER)
    )

    for bucket in (result.added, result.resolved, result.carried):
        [finding] = bucket
        assert finding.raw_evidence is None
        assert finding.snippet is None
        assert finding.file_path is None
        assert finding.line_number is None


def test_get_repository_diff_leaves_sensitive_fields_intact_for_admin_in_every_set() -> None:
    repo = _make_repository()
    latest_run = _make_run(repository_id=repo.id)
    baseline_run = _make_run(repository_id=repo.id)
    repository_port = _FakeCodeRepositoryRepository([repo])
    scan_run_port = _FakeScanRunRepository(recent_completed=[latest_run, baseline_run])
    added_finding = _make_finding()
    resolved_finding = _make_finding()
    carried_finding = _make_finding()
    finding_port = _FakeFindingRepository(
        diff_sets=FindingDiffSets(
            added=[added_finding], resolved=[resolved_finding], carried=[carried_finding]
        )
    )

    result = asyncio.run(
        get_repository_diff(repository_port, scan_run_port, finding_port, repo.id, UserRole.ADMIN)
    )

    assert result.added[0].raw_evidence == added_finding.raw_evidence
    assert result.added[0].snippet == added_finding.snippet
    assert result.resolved[0].file_path == resolved_finding.file_path
    assert result.resolved[0].line_number == resolved_finding.line_number
    assert result.carried[0].raw_evidence == carried_finding.raw_evidence
    assert result.carried[0].snippet == carried_finding.snippet
