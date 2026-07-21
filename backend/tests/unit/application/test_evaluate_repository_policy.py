"""`evaluate_repository_policy` use case — repo-scoped pure threshold over
`FindingPort.open_counts_by_severity` (Module 12a). Powers
`GET /repositories/{id}/policy-check`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.evaluate_repository_policy import (
    evaluate_repository_policy,
)
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingDiffSets, FindingPort, FindingTrendBucket
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    RepositoryProvider,
    ScannerType,
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


class _FakeFindingRepository(FindingPort):
    def __init__(self, *, open_counts: dict[FindingSeverity, int] | None = None) -> None:
        self._open_counts = open_counts or {}
        self.open_calls: list[uuid.UUID] = []

    async def get_by_id(self, finding_id: uuid.UUID) -> object:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[object]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def create(self, finding: object) -> object:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def update_status(self, finding_id: uuid.UUID, status: object) -> object:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[object]
    ) -> None:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[object]:
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
    ) -> list[object]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def trend_counts_by_first_seen_run(
        self,
        repository_id: uuid.UUID,
        *,
        scanner_type: ScannerType | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[FindingTrendBucket]:
        raise NotImplementedError  # pragma: no cover — unused in these tests

    async def open_counts_by_severity(self, repository_id: uuid.UUID) -> dict[FindingSeverity, int]:
        self.open_calls.append(repository_id)
        return self._open_counts

    async def diff_between_runs(
        self, repository_id: uuid.UUID, latest_run_id: uuid.UUID, baseline_run_id: uuid.UUID
    ) -> FindingDiffSets:
        raise NotImplementedError  # pragma: no cover — unused in these tests


def test_evaluate_repository_policy_raises_not_found_for_missing_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository([])
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(evaluate_repository_policy(repository_port, finding_port, uuid.uuid4()))


def test_evaluate_repository_policy_raises_not_found_for_inactive_repository() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(evaluate_repository_policy(repository_port, finding_port, repo.id))


def test_evaluate_repository_policy_fails_with_open_critical_findings() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository(open_counts={FindingSeverity.CRITICAL: 2})

    result = asyncio.run(evaluate_repository_policy(repository_port, finding_port, repo.id))

    assert result.repository_id == repo.id
    assert result.verdict == "fail"
    assert result.violating_counts == {FindingSeverity.CRITICAL: 2}
    assert result.blocking_severities == [FindingSeverity.CRITICAL, FindingSeverity.HIGH]
    assert finding_port.open_calls == [repo.id]


def test_evaluate_repository_policy_passes_with_only_medium_and_low_open() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository(
        open_counts={FindingSeverity.MEDIUM: 5, FindingSeverity.LOW: 10}
    )

    result = asyncio.run(evaluate_repository_policy(repository_port, finding_port, repo.id))

    assert result.verdict == "pass"
    assert result.violating_counts == {}


def test_evaluate_repository_policy_passes_with_no_findings_ever() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository()

    result = asyncio.run(evaluate_repository_policy(repository_port, finding_port, repo.id))

    assert result.verdict == "pass"
    assert result.violating_counts == {}


def test_evaluate_repository_policy_sparse_dict_only_medium_key_present() -> None:
    """CRITICAL/HIGH keys are entirely ABSENT from the port's dict (not
    present-with-zero) — the sparse edge case direct-indexing code would
    break on."""
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository(open_counts={FindingSeverity.MEDIUM: 3})

    result = asyncio.run(evaluate_repository_policy(repository_port, finding_port, repo.id))

    assert result.verdict == "pass"
    assert result.violating_counts == {}
