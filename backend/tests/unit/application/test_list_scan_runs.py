"""`list_scan_runs` use case — thin pagination pass-through to `ScanRunPort.list_paginated`."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.list_scan_runs import list_scan_runs
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import ScanRunStatus

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ScanRun] = {}
        self.last_call: tuple[int, int] | None = None

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
        self.last_call = (limit, offset)
        ordered = sorted(self._by_id.values(), key=lambda r: r.created_at, reverse=True)
        return ordered[offset : offset + limit]


def _make_run(**overrides: object) -> ScanRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "repository_id": uuid.uuid4(),
        "status": ScanRunStatus.PENDING,
        "trigger": "manual",
        "commit_sha": "abc123",
        "ref": "abc123",
        "created_at": _NOW,
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(overrides)
    return ScanRun(**defaults)  # type: ignore[arg-type]


def test_list_scan_runs_returns_empty_list_when_none_exist() -> None:
    scan_run_port = _FakeScanRunRepository()

    result = asyncio.run(list_scan_runs(scan_run_port))

    assert result == []


def test_list_scan_runs_forwards_limit_and_offset_to_the_port() -> None:
    scan_run_port = _FakeScanRunRepository()
    for i in range(3):
        scan_run_port.seed(_make_run(created_at=datetime(2026, 1, 1 + i)))

    result = asyncio.run(list_scan_runs(scan_run_port, limit=1, offset=1))

    assert scan_run_port.last_call == (1, 1)
    assert len(result) == 1


def test_list_scan_runs_defaults_to_limit_20_offset_0() -> None:
    scan_run_port = _FakeScanRunRepository()
    run = _make_run()
    scan_run_port.seed(run)

    result = asyncio.run(list_scan_runs(scan_run_port))

    assert scan_run_port.last_call == (20, 0)
    assert result == [run]
