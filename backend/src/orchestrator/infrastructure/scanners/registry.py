"""`ScannerType -> ScannerAdapterPort` registry/factory (Module 7 D2; Module
11 adds the `SCA` and `SAST` registrations).

`ScannerType.SECRETS` (Gitleaks), `ScannerType.SCA` (pip-audit), and
`ScannerType.SAST` (`AstSastAdapter`) have real registrations; every other
`ScannerType` raises `UnregisteredScannerError` until a future module adds
its adapter. `image_ref`/`default_args` are carried on the registration for
future tools, but every adapter keeps sourcing its image/args from
`Settings`/its own module constants for now (D2 — avoids refactoring
`.scan()` in this module).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.scanners.ast_sast_adapter import (
    _SAST_ARGV,
    AstSastAdapter,
)
from orchestrator.infrastructure.scanners.gitleaks_adapter import (
    _GITLEAKS_ARGV,
    GitleaksAdapter,
)
from orchestrator.infrastructure.scanners.pip_audit_adapter import (
    _PIP_AUDIT_ARGV,
    PipAuditAdapter,
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

#: Locally-built from `docker/pip-audit.Dockerfile` (which pins its own
#: `python:3.12-slim` base by digest and `pip-audit` by exact version) — no
#: registry digest to pin here since the image is never pushed (Module 11).
_PIP_AUDIT_IMAGE_REF = "pip-audit-scanner:local"

#: Locally-built from `docker/sast-scanner.Dockerfile` (which pins its own
#: `python:3.12-slim` base by digest and the `sast-scanner` source by exact
#: commit SHA) — no registry digest to pin here since the image is never
#: pushed (Module 11).
_SAST_IMAGE_REF = "sast-scanner:local"


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
    ScannerType.SCA: ScannerRegistration(
        image_ref=_PIP_AUDIT_IMAGE_REF,
        adapter_class=PipAuditAdapter,
        default_args=_PIP_AUDIT_ARGV,
    ),
    ScannerType.SAST: ScannerRegistration(
        image_ref=_SAST_IMAGE_REF,
        adapter_class=AstSastAdapter,
        default_args=_SAST_ARGV,
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
