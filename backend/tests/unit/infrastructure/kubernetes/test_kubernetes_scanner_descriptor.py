"""`resolve_kubernetes_scanner` — SECRETS-only, fail-closed for every other
`ScannerType` (k8s-backend-enable PR5, tasks 5.11-5.12)."""

from __future__ import annotations

import pytest

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_scanner_descriptor import (
    REVPARSE_ARGV,
    UnsupportedScannerTypeError,
    resolve_kubernetes_scanner,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "database_url": "postgresql://o:o@localhost/o",
        "redis_url": "redis://localhost:6379/0",
        "secret_key": "s",
        "jwt_secret_key": "j",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_secrets_resolves_to_the_gitleaks_image_and_workspace_targeted_argv() -> None:
    settings = _settings()

    image, argv = resolve_kubernetes_scanner(ScannerType.SECRETS, settings)

    assert image == settings.scan_container_image
    assert "/workspace/checkout" in argv
    assert "--exit-code=2" in argv


@pytest.mark.parametrize(
    "scanner_type",
    [ScannerType.SAST, ScannerType.SCA, ScannerType.IAC, ScannerType.SEMGREP, ScannerType.DAST],
)
def test_every_other_scanner_type_raises_unsupported(scanner_type: ScannerType) -> None:
    with pytest.raises(UnsupportedScannerTypeError):
        resolve_kubernetes_scanner(scanner_type, _settings())


def test_revparse_argv_targets_the_workspace_checkout_via_the_git_entrypoint() -> None:
    assert REVPARSE_ARGV == ("-C", "/workspace/checkout", "rev-parse", "HEAD")
