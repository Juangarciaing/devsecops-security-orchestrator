"""`get_scan_target` use case — treats an inactive target as gone
(dast-scanner PR6, mirrors `test_get_repository.py`)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.get_scan_target import (
    ScanTargetNotFoundError,
    get_scan_target,
)
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeScanTargetRepository(ScanTargetPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ScanTarget] = {}

    def seed(self, target: ScanTarget) -> None:
        self._by_id[target.id] = target

    async def get_by_id(self, target_id: uuid.UUID) -> ScanTarget | None:
        return self._by_id.get(target_id)

    async def get_by_url(self, target_url: str) -> ScanTarget | None:
        return None

    async def list_all(self) -> list[ScanTarget]:
        return list(self._by_id.values())

    async def list_active(self) -> list[ScanTarget]:
        return [t for t in self._by_id.values() if t.is_active]

    async def create(self, target: ScanTarget) -> ScanTarget:
        self._by_id[target.id] = target
        return target

    async def update(self, target: ScanTarget) -> ScanTarget:
        self._by_id[target.id] = target
        return target

    async def soft_delete(self, target_id: uuid.UUID) -> None:
        target = self._by_id.get(target_id)
        if target is not None:
            target.is_active = False


def _make_target(**overrides: object) -> ScanTarget:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "acme-site",
        "target_url": "https://public.example.com",
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return ScanTarget(**defaults)  # type: ignore[arg-type]


def test_get_scan_target_raises_not_found_for_absent_id() -> None:
    target_port = _FakeScanTargetRepository()

    with pytest.raises(ScanTargetNotFoundError):
        asyncio.run(get_scan_target(target_port, uuid.uuid4()))


def test_get_scan_target_raises_not_found_for_inactive_target() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target(is_active=False)
    target_port.seed(target)

    with pytest.raises(ScanTargetNotFoundError):
        asyncio.run(get_scan_target(target_port, target.id))


def test_get_scan_target_returns_active_target() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    target_port.seed(target)

    result = asyncio.run(get_scan_target(target_port, target.id))

    assert result == target
