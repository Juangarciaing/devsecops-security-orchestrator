"""`get_scan_run_detail` use case — composes `ScanRun` + its `ScanTask` + a
findings count (spec: `GET /scans/{id}` returns a count, never a findings list).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_scan_run_detail import (
    ScanRunNotFoundError,
    get_scan_run_detail,
)
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus

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
        return []  # pragma: no cover — unused in these tests


class _FakeScanTaskRepository(ScanTaskPort):
    def __init__(self) -> None:
        self._by_run: dict[uuid.UUID, list[ScanTask]] = {}

    def seed(self, task: ScanTask) -> None:
        self._by_run.setdefault(task.scan_run_id, []).append(task)

    async def get_by_id(self, scan_task_id: uuid.UUID) -> ScanTask | None:
        for tasks in self._by_run.values():
            for task in tasks:
                if task.id == scan_task_id:
                    return task
        return None

    async def list_by_scan_run(self, scan_run_id: uuid.UUID) -> list[ScanTask]:
        return self._by_run.get(scan_run_id, [])

    async def create(self, scan_task: ScanTask) -> ScanTask:
        self.seed(scan_task)
        return scan_task

    async def update_status(
        self, scan_task_id: uuid.UUID, status: ScanTaskStatus
    ) -> ScanTask:  # pragma: no cover — unused in these tests, only present to satisfy the ABC
        task = await self.get_by_id(scan_task_id)
        assert task is not None
        task.status = status
        return task

    async def find_active_task(
        self, repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        return None  # pragma: no cover — unused in tests


class _FakeFindingCounter:
    def __init__(self, count: int) -> None:
        self._count = count
        self.calls: list[uuid.UUID] = []

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        self.calls.append(scan_run_id)
        return self._count


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


def _make_task(scan_run_id: uuid.UUID, **overrides: object) -> ScanTask:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "scan_run_id": scan_run_id,
        "scanner_type": ScannerType.SECRETS,
        "status": ScanTaskStatus.COMPLETED,
        "started_at": _NOW,
        "completed_at": _NOW,
        "error_message": None,
    }
    defaults.update(overrides)
    return ScanTask(**defaults)  # type: ignore[arg-type]


def test_get_scan_run_detail_raises_not_found_for_absent_run() -> None:
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()
    finding_counter = _FakeFindingCounter(0)

    with pytest.raises(ScanRunNotFoundError):
        asyncio.run(
            get_scan_run_detail(scan_run_port, scan_task_port, finding_counter, uuid.uuid4())
        )


def test_get_scan_run_detail_returns_run_task_and_findings_count() -> None:
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()
    run = _make_run()
    task = _make_task(run.id)
    scan_run_port.seed(run)
    scan_task_port.seed(task)
    finding_counter = _FakeFindingCounter(1)

    result_run, result_task, count = asyncio.run(
        get_scan_run_detail(scan_run_port, scan_task_port, finding_counter, run.id)
    )

    assert result_run.id == run.id
    assert result_task.id == task.id
    assert count == 1
    assert finding_counter.calls == [run.id]


def test_get_scan_run_detail_findings_count_can_be_zero_for_pending_scan() -> None:
    scan_run_port = _FakeScanRunRepository()
    scan_task_port = _FakeScanTaskRepository()
    run = _make_run(status=ScanRunStatus.PENDING, started_at=None, completed_at=None)
    task = _make_task(run.id, status=ScanTaskStatus.PENDING, started_at=None, completed_at=None)
    scan_run_port.seed(run)
    scan_task_port.seed(task)
    finding_counter = _FakeFindingCounter(0)

    _, _, count = asyncio.run(
        get_scan_run_detail(scan_run_port, scan_task_port, finding_counter, run.id)
    )

    assert count == 0
