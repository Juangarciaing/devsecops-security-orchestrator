"""`ScannerType -> ScannerAdapterPort` registry/factory (Module 7 D2).

Only `ScannerType.SECRETS` (Gitleaks) has a real registration today; every
other `ScannerType` raises `UnregisteredScannerError` until a future module
adds its adapter. `image_ref`/`default_args` are carried on the
registration for future tools, but `GitleaksAdapter` keeps sourcing its
image/args from `Settings`/its own module constants for now (D2 — avoids
refactoring `GitleaksAdapter.scan()` in this module).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.scanners.gitleaks_adapter import (
    _GITLEAKS_ARGV,
    GitleaksAdapter,
)

if TYPE_CHECKING:
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
    from orchestrator.infrastructure.config.settings import Settings


class _AdapterFactory(Protocol):
    """Constructor shape every registered adapter class MUST match: `(runner,
    settings) -> ScannerAdapterPort` — precisely `GitleaksAdapter.__init__`'s
    signature (D2)."""

    def __call__(self, runner: ContainerRunnerPort, settings: Settings) -> ScannerAdapterPort: ...


#: Tag+digest-pinned per `Settings.scan_container_image` (Module 6) —
#: informational only; the adapter itself still reads the live value from
#: `Settings` at construction time (D2).
_GITLEAKS_IMAGE_REF = (
    "ghcr.io/gitleaks/gitleaks:v8.30.1"
    "@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
)


class UnregisteredScannerError(Exception):
    """Raised by `get_adapter()` when `scanner_type` has no registration."""

    def __init__(self, scanner_type: ScannerType) -> None:
        super().__init__(f"no adapter registered for scanner type: {scanner_type}")
        self.scanner_type = scanner_type


@dataclass(frozen=True, slots=True)
class ScannerRegistration:
    """One `ScannerType`'s adapter binding."""

    image_ref: str
    adapter_class: _AdapterFactory
    default_args: tuple[str, ...] = ()


_REGISTRY: dict[ScannerType, ScannerRegistration] = {
    ScannerType.SECRETS: ScannerRegistration(
        image_ref=_GITLEAKS_IMAGE_REF,
        adapter_class=GitleaksAdapter,
        default_args=_GITLEAKS_ARGV,
    ),
}


def get_adapter(
    scanner_type: ScannerType,
    runner: ContainerRunnerPort,
    settings: Settings,
) -> ScannerAdapterPort:
    """Instantiate the `ScannerAdapterPort` registered for `scanner_type`.

    Raises `UnregisteredScannerError` if no adapter is registered.
    """
    registration = _REGISTRY.get(scanner_type)
    if registration is None:
        raise UnregisteredScannerError(scanner_type)
    return registration.adapter_class(runner, settings)
