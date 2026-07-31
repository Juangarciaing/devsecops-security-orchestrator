"""`list_scan_targets` use case — returns only active `ScanTarget` rows
(dast-scanner PR6, mirrors `test_list_repositories.py`-equivalent shape)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.list_scan_targets import list_scan_targets
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


def test_list_scan_targets_returns_only_active_targets() -> None:
    target_port = _FakeScanTargetRepository()
    active = _make_target()
    inactive = _make_target(is_active=False)
    target_port.seed(active)
    target_port.seed(inactive)

    result = asyncio.run(list_scan_targets(target_port))

    assert result == [active]


def test_list_scan_targets_returns_empty_list_when_none_registered() -> None:
    target_port = _FakeScanTargetRepository()

    result = asyncio.run(list_scan_targets(target_port))

    assert result == []
