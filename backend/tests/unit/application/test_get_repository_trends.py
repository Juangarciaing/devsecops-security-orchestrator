"""`get_repository_trends` use case — repo-scoped, exact introduced-per-run
(by severity) plus current-open snapshot. Powers `GET /repositories/{id}/trends`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.get_repository_trends import get_repository_trends
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort, FindingTrendBucket
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
    def __init__(
        self,
        *,
        buckets: list[FindingTrendBucket] | None = None,
        open_counts: dict[FindingSeverity, int] | None = None,
    ) -> None:
        self._buckets = buckets or []
        self._open_counts = open_counts or {}
        self.trend_calls: list[dict[str, object]] = []
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
        self.trend_calls.append(
            {
                "repository_id": repository_id,
                "scanner_type": scanner_type,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            }
        )
        return self._buckets

    async def open_counts_by_severity(self, repository_id: uuid.UUID) -> dict[FindingSeverity, int]:
        self.open_calls.append(repository_id)
        return self._open_counts


def test_get_repository_trends_assembles_dto_from_port_buckets() -> None:
    repo = _make_repository()
    run_id = uuid.uuid4()
    bucket = FindingTrendBucket(
        scan_run_id=run_id,
        occurred_at=_NOW,
        commit_sha="abc123",
        severity_counts={FindingSeverity.HIGH: 2},
    )
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository(buckets=[bucket], open_counts={FindingSeverity.HIGH: 2})

    result = asyncio.run(get_repository_trends(repository_port, finding_port, repo.id))

    assert result.repository_id == repo.id
    assert len(result.points) == 1
    assert result.points[0].scan_run_id == run_id
    assert result.points[0].commit_sha == "abc123"
    assert result.points[0].introduced == {FindingSeverity.HIGH: 2}
    assert result.current_open == {FindingSeverity.HIGH: 2}
    assert finding_port.trend_calls == [
        {
            "repository_id": repo.id,
            "scanner_type": None,
            "date_from": None,
            "date_to": None,
            "limit": 100,
        }
    ]
    assert finding_port.open_calls == [repo.id]


def test_get_repository_trends_empty_repository_returns_empty_points_and_zero_open() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository()

    result = asyncio.run(get_repository_trends(repository_port, finding_port, repo.id))

    assert result.points == []
    assert result.current_open == {}


def test_get_repository_trends_passes_scanner_type_filter_through_to_the_port() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository()

    asyncio.run(
        get_repository_trends(
            repository_port, finding_port, repo.id, scanner_type=ScannerType.SEMGREP
        )
    )

    assert finding_port.trend_calls[0]["scanner_type"] == ScannerType.SEMGREP


def test_get_repository_trends_raises_not_found_for_missing_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository([])
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(get_repository_trends(repository_port, finding_port, uuid.uuid4()))


def test_get_repository_trends_raises_not_found_for_inactive_repository() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])
    finding_port = _FakeFindingRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(get_repository_trends(repository_port, finding_port, repo.id))
