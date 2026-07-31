"""`register_scan_target` use case — registration-time URL validation +
duplicate `target_url` rejection (dast-scanner PR6, mirrors
`test_register_repository.py`)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.application.use_cases.register_scan_target import (
    DuplicateTargetUrlError,
    register_scan_target,
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


def test_register_scan_target_creates_active_target() -> None:
    target_port = _FakeScanTargetRepository()

    created = asyncio.run(
        register_scan_target(target_port, "acme-site", "https://public.example.com")
    )

    assert created.name == "acme-site"
    assert created.target_url == "https://public.example.com"
    assert created.is_active is True


def test_register_scan_target_rejects_duplicate_target_url() -> None:
    target_port = _FakeScanTargetRepository()
    target_port.seed(
        ScanTarget(
            id=uuid.uuid4(),
            name="existing",
            target_url="https://public.example.com",
            is_active=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    with pytest.raises(DuplicateTargetUrlError):
        asyncio.run(
            register_scan_target(target_port, "acme-site", "https://public.example.com")
        )


def test_register_scan_target_rejects_duplicate_target_url_even_when_inactive() -> None:
    target_port = _FakeScanTargetRepository()
    target_port.seed(
        ScanTarget(
            id=uuid.uuid4(),
            name="existing",
            target_url="https://public.example.com",
            is_active=False,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    with pytest.raises(DuplicateTargetUrlError):
        asyncio.run(
            register_scan_target(target_port, "acme-site", "https://public.example.com")
        )


def test_register_scan_target_rejects_a_private_ip_literal() -> None:
    target_port = _FakeScanTargetRepository()

    with pytest.raises(InvalidTargetUrlError):
        asyncio.run(register_scan_target(target_port, "internal", "http://127.0.0.1"))


def test_register_scan_target_rejects_an_unsupported_scheme() -> None:
    target_port = _FakeScanTargetRepository()

    with pytest.raises(InvalidTargetUrlError):
        asyncio.run(register_scan_target(target_port, "ftp-target", "ftp://example.com"))
