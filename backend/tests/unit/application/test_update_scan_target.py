"""`update_scan_target` use case — mutable-fields-only PATCH (dast-scanner
PR6, mirrors `test_update_repository.py`)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.dto.scan_target import ScanTargetUpdate
from orchestrator.application.use_cases.get_scan_target import ScanTargetNotFoundError
from orchestrator.application.use_cases.register_scan_target import DuplicateTargetUrlError
from orchestrator.application.use_cases.update_scan_target import (
    InvalidScanTargetUpdateError,
    update_scan_target,
)
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort
from orchestrator.domain.services.target_url_policy import InvalidTargetUrlError

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeScanTargetRepository(ScanTargetPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, ScanTarget] = {}

    def seed(self, target: ScanTarget) -> None:
        self._by_id[target.id] = target

    async def get_by_id(self, target_id: uuid.UUID) -> ScanTarget | None:
        return self._by_id.get(target_id)

    async def get_by_url(self, target_url: str) -> ScanTarget | None:
        for target in self._by_id.values():
            if target.target_url == target_url:
                return target
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


def test_update_scan_target_raises_not_found_for_absent_id() -> None:
    target_port = _FakeScanTargetRepository()

    with pytest.raises(ScanTargetNotFoundError):
        asyncio.run(update_scan_target(target_port, uuid.uuid4(), ScanTargetUpdate(name="new")))


def test_update_scan_target_raises_not_found_for_inactive_target() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target(is_active=False)
    target_port.seed(target)

    with pytest.raises(ScanTargetNotFoundError):
        asyncio.run(update_scan_target(target_port, target.id, ScanTargetUpdate(name="new")))


def test_update_scan_target_applies_only_provided_fields() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    target_port.seed(target)

    updated = asyncio.run(
        update_scan_target(target_port, target.id, ScanTargetUpdate(name="renamed"))
    )

    assert updated.name == "renamed"
    assert updated.target_url == "https://public.example.com"


def test_update_scan_target_rejects_explicit_null_name() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    target_port.seed(target)

    with pytest.raises(InvalidScanTargetUpdateError):
        asyncio.run(update_scan_target(target_port, target.id, ScanTargetUpdate(name=None)))


def test_update_scan_target_rejects_explicit_null_target_url() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    target_port.seed(target)

    with pytest.raises(InvalidScanTargetUpdateError):
        asyncio.run(
            update_scan_target(target_port, target.id, ScanTargetUpdate(target_url=None))
        )


def test_update_scan_target_revalidates_new_url_shape() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    target_port.seed(target)

    with pytest.raises(InvalidTargetUrlError):
        asyncio.run(
            update_scan_target(
                target_port, target.id, ScanTargetUpdate(target_url="http://127.0.0.1")
            )
        )


def test_update_scan_target_rejects_duplicate_url_owned_by_another_target() -> None:
    target_port = _FakeScanTargetRepository()
    target = _make_target()
    other = _make_target(id=uuid.uuid4(), target_url="https://other.example.com")
    target_port.seed(target)
    target_port.seed(other)

    with pytest.raises(DuplicateTargetUrlError):
        asyncio.run(
            update_scan_target(
                target_port, target.id, ScanTargetUpdate(target_url="https://other.example.com")
            )
        )
