"""`infrastructure/scanners/registry.py` — `ScannerType -> ScannerAdapterPort`
factory (Module 7 D2, tasks 1.3-1.4).

Only `ScannerType.SECRETS` has a real registration (Gitleaks); every other
`ScannerType` raises `UnregisteredScannerError` until a future module adds
its adapter.
"""

from __future__ import annotations

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksAdapter
from tests.fakes.fake_container_runner import FakeContainerRunner


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_get_adapter_resolves_gitleaks_adapter_for_secrets() -> None:
    from orchestrator.infrastructure.scanners.registry import get_adapter

    adapter = get_adapter(ScannerType.SECRETS, FakeContainerRunner(), _settings())

    assert isinstance(adapter, GitleaksAdapter)


def test_get_adapter_returns_an_adapter_that_implements_the_port_contract() -> None:
    from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
    from orchestrator.infrastructure.scanners.registry import get_adapter

    adapter = get_adapter(ScannerType.SECRETS, FakeContainerRunner(), _settings())

    assert isinstance(adapter, ScannerAdapterPort)
    assert adapter.supports(ScannerType.SECRETS) is True


def test_get_adapter_raises_unregistered_scanner_error_for_sast() -> None:
    from orchestrator.infrastructure.scanners.registry import (
        UnregisteredScannerError,
        get_adapter,
    )

    try:
        get_adapter(ScannerType.SAST, FakeContainerRunner(), _settings())
    except UnregisteredScannerError as exc:
        assert "sast" in str(exc).lower()
    else:
        raise AssertionError("expected UnregisteredScannerError")


def test_get_adapter_raises_unregistered_scanner_error_for_dast() -> None:
    from orchestrator.infrastructure.scanners.registry import (
        UnregisteredScannerError,
        get_adapter,
    )

    try:
        get_adapter(ScannerType.DAST, FakeContainerRunner(), _settings())
    except UnregisteredScannerError:
        pass
    else:
        raise AssertionError("expected UnregisteredScannerError")
