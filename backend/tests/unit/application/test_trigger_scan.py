"""`trigger_scan` use case — idempotent scan trigger, no enqueueing (D4).

Enqueueing `.delay()` is explicitly NOT this use case's job — see
`sdd/module-5-scan-orchestration-skeleton/design` D4. These tests only prove
the DB-side idempotency check and `ScanRun`/`ScanTask` creation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.trigger_scan import trigger_scan
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.value_objects.enums import (
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, CodeRepository] = {}

    def seed(self, repository: CodeRepository) -> None:
        self._by_id[repository.id] = repository

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        return self._by_id.get(repository_id)

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        for repo in self._by_id.values():
            if repo.identity() == (provider, owner, name):
                return repo
        return None

    async def list_all(self) -> list[CodeRepository]:
        return list(self._by_id.values())

    async def list_active(self) -> list[CodeRepository]:
        return [r for r in self._by_id.values() if r.is_active]

    async def create(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        return repository

    async def update(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        return repository

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        repo = self._by_id.get(repository_id)
        if repo is not None:
            repo.is_active = False

    async def delete(self, repository_id: uuid.UUID) -> None:
        self._by_id.pop(repository_id, None)


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self) -> None:
        self.created: list[ScanRun] = []
        self._by_id: dict[uuid.UUID, ScanRun] = {}

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        return self._by_id.get(scan_run_id)

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        return [r for r in self._by_id.values() if r.repository_id == repository_id]

    async def create(self, scan_run: ScanRun) -> ScanRun:
        self._by_id[scan_run.id] = scan_run
        self.created.append(scan_run)
        return scan_run

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        run = self._by_id[scan_run_id]
        run.status = status
        return run

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        ordered = sorted(self._by_id.values(), key=lambda r: r.created_at, reverse=True)
        return ordered[offset : offset + limit]

    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        return []  # pragma: no cover — unused in these tests


class _FakeScanTaskRepository(ScanTaskPort):
    def __init__(self) -> None:
        self.created: list[ScanTask] = []
        self._by_id: dict[uuid.UUID, ScanTask] = {}
        self._runs_by_task: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}

    async def get_by_id(self, scan_task_id: uuid.UUID) -> ScanTask | None:
        return self._by_id.get(scan_task_id)

    async def list_by_scan_run(self, scan_run_id: uuid.UUID) -> list[ScanTask]:
        return [t for t in self._by_id.values() if t.scan_run_id == scan_run_id]

    async def create(self, scan_task: ScanTask) -> ScanTask:
        self._by_id[scan_task.id] = scan_task
        self.created.append(scan_task)
        return scan_task

    async def update_status(self, scan_task_id: uuid.UUID, status: ScanTaskStatus) -> ScanTask:
        task = self._by_id[scan_task_id]
        task.status = status
        return task

    async def find_active_task(
        self, repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        # Fake join: `register_run_for_task` seeds the (repository_id, commit_sha)
        # this fake would otherwise resolve via a real SQL join in production.
        for task in self._by_id.values():
            if (
                task.scanner_type == scanner_type
                and task.status in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING)
                and self._runs_by_task.get(task.id) == (repository_id, commit_sha)
            ):
                return task
        return None

    def register_run_for_task(
        self, task_id: uuid.UUID, repository_id: uuid.UUID, commit_sha: str
    ) -> None:
        self._runs_by_task[task_id] = (repository_id, commit_sha)


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


def test_trigger_scan_raises_not_found_for_absent_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(trigger_scan(repository_port, scan_run_port, scan_task_port, uuid.uuid4()))


def test_trigger_scan_raises_not_found_for_inactive_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository(is_active=False)
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    with pytest.raises(RepositoryNotFoundError):
        asyncio.run(trigger_scan(repository_port, scan_run_port, scan_task_port, repository.id))


def test_trigger_scan_creates_run_and_task_on_first_trigger() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository()
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    run, created = asyncio.run(
        trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository.id,
            commit_sha="abc123",
        )
    )

    assert created is True
    assert run.status == ScanRunStatus.PENDING
    assert run.trigger == "manual"
    assert run.commit_sha == "abc123"
    assert run.ref == "abc123"
    assert len(scan_run_port.created) == 1
    assert len(scan_task_port.created) == 1
    assert scan_task_port.created[0].scanner_type == ScannerType.SECRETS
    assert scan_task_port.created[0].status == ScanTaskStatus.PENDING
    assert scan_task_port.created[0].scan_run_id == run.id


def test_trigger_scan_missing_commit_sha_defaults_to_default_branch() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository(default_branch="develop")
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    run, created = asyncio.run(
        trigger_scan(repository_port, scan_run_port, scan_task_port, repository.id)
    )

    assert created is True
    assert run.commit_sha == "develop"
    assert run.ref == "develop"


def test_trigger_scan_defaults_trigger_to_manual_when_omitted() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository()
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    run, _created = asyncio.run(
        trigger_scan(repository_port, scan_run_port, scan_task_port, repository.id)
    )

    assert run.trigger == "manual"


def test_trigger_scan_propagates_an_explicit_webhook_trigger() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository()
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    run, created = asyncio.run(
        trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository.id,
            commit_sha="abc123",
            trigger="webhook",
        )
    )

    assert created is True
    assert run.trigger == "webhook"


def test_trigger_scan_returns_existing_run_when_active_task_exists() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    repository = _make_repository()
    repository_port.seed(repository)
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()

    first_run, first_created = asyncio.run(
        trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository.id,
            commit_sha="abc123",
        )
    )
    assert first_created is True

    scan_task_port.register_run_for_task(scan_task_port.created[0].id, repository.id, "abc123")

    second_run, second_created = asyncio.run(
        trigger_scan(
            repository_port,
            scan_run_port,
            scan_task_port,
            repository.id,
            commit_sha="abc123",
        )
    )

    assert second_created is False
    assert second_run.id == first_run.id
    assert len(scan_run_port.created) == 1
    assert len(scan_task_port.created) == 1
