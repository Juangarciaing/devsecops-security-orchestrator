"""Kubernetes-specific scanner image/argv descriptor (k8s-backend-enable
PR5, design D-Result d).

`gitleaks_descriptor.py`'s `_GITLEAKS_ARGV` hardcodes `/checkout/checkout`
(Docker's named-volume mount layout, `GitleaksInvocation.mount_path`) — the
Kubernetes split-workload PVC layout is `/workspace/checkout` instead
(`kubernetes_scan_execution.py`'s checkout Job clones there). This module is
the k8s-only sibling: `resolve_kubernetes_scanner` registers ONLY
`ScannerType.SECRETS`, fail-closed for every other type — mirroring
`create_scan_execution`'s inverted, explicit-registration contract in
`scan_execution_factory.py` (reused here rather than duplicated) — public-
image-only is enforced structurally, not by a runtime `ErrImagePull`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestrator.domain.value_objects.enums import ScannerType

if TYPE_CHECKING:
    from orchestrator.infrastructure.config.settings import Settings

__all__ = ["REVPARSE_ARGV", "UnsupportedScannerTypeError", "resolve_kubernetes_scanner"]

_K8S_TARGET_DIR = "/workspace/checkout"


class UnsupportedScannerTypeError(ValueError):
    """Raised by `resolve_kubernetes_scanner()` when `scanner_type` has no
    Kubernetes scanner descriptor registered — mirrors
    `scan_execution_factory.UnsupportedScannerTypeError`'s contract
    (same name, same fail-closed behavior), kept as a DISTINCT class here
    rather than reused/imported so the message stays honest about which
    backend (Kubernetes, not Docker) rejected the scanner type."""

    def __init__(self, scanner_type: ScannerType) -> None:
        super().__init__(
            f"no Kubernetes scanner descriptor registered for scanner type: {scanner_type.value}"
        )
        self.scanner_type = scanner_type

#: Same Gitleaks flags as the Docker path (`gitleaks_descriptor._GITLEAKS_ARGV`)
#: — only the target directory differs (PVC layout, not a named volume).
_GITLEAKS_K8S_ARGV: tuple[str, ...] = (
    "dir",
    _K8S_TARGET_DIR,
    "--report-format=json",
    "--report-path=/dev/stdout",
    "--exit-code=2",
    "--no-banner",
)

#: The bounded rev-parse Job's argv (design D-Result c) — relies on the
#: `alpine/git` ENTRYPOINT exactly like the checkout Job's clone argv does.
REVPARSE_ARGV: tuple[str, ...] = ("-C", _K8S_TARGET_DIR, "rev-parse", "HEAD")


def resolve_kubernetes_scanner(
    scanner_type: ScannerType, settings: Settings
) -> tuple[str, list[str]]:
    """Resolve `scanner_type` to its `(image, argv)` Kubernetes invocation.

    `ScannerType.SECRETS` is the only registered type — reuses
    `settings.scan_container_image` (the same digest-pinned Gitleaks image
    the Docker path already trusts; this backend introduces no new image).
    Every other `ScannerType` raises `UnsupportedScannerTypeError` — a
    scanner whose image is `*-scanner:local` (semgrep/pip-audit/ast-sast) is
    structurally unreachable on this backend, never an `ErrImagePull`.
    """
    if scanner_type == ScannerType.SECRETS:
        return settings.scan_container_image, list(_GITLEAKS_K8S_ARGV)
    raise UnsupportedScannerTypeError(scanner_type)
