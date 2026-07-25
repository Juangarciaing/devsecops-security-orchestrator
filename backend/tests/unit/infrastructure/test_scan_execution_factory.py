"""Exhaustive supported/unsupported routing contract for `create_scan_execution`
(PR5b): every supported `ScannerType` MUST select exactly one descriptor Docker
execution, and every unsupported type MUST raise deterministically — never
falling back to a shared/legacy execution path (`LegacyDockerExecution` is
removed by this same slice).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.container.ast_sast_docker_execution import AstSastDockerExecution
from orchestrator.infrastructure.container.gitleaks_docker_execution import GitleaksDockerExecution
from orchestrator.infrastructure.container.pip_audit_docker_execution import PipAuditDockerExecution
from orchestrator.infrastructure.container.scan_execution_factory import (
    UnsupportedScannerTypeError,
    create_scan_execution,
)
from orchestrator.infrastructure.container.semgrep_docker_execution import SemgrepDockerExecution

_SUPPORTED_CASES = [
    (ScannerType.SECRETS, GitleaksDockerExecution),
    (ScannerType.SAST, AstSastDockerExecution),
    (ScannerType.SEMGREP, SemgrepDockerExecution),
    (ScannerType.SCA, PipAuditDockerExecution),
]


@pytest.mark.parametrize(("scanner_type", "execution_class"), _SUPPORTED_CASES)
def test_factory_selects_exactly_one_descriptor_executor_per_supported_type(
    scanner_type: ScannerType, execution_class: type[object]
) -> None:
    execution = create_scan_execution(MagicMock(), MagicMock(), SimpleNamespace(), scanner_type)

    # Exact-class check (not just isinstance) — proves no other supported
    # type's descriptor is silently substituted.
    assert execution.__class__ is execution_class


def test_factory_selects_a_different_class_per_supported_type() -> None:
    dependencies = (MagicMock(), MagicMock(), SimpleNamespace())
    executions = {
        scanner_type: create_scan_execution(*dependencies, scanner_type)
        for scanner_type, _ in _SUPPORTED_CASES
    }

    assert len({type(execution) for execution in executions.values()}) == len(_SUPPORTED_CASES)


@pytest.mark.parametrize("scanner_type", [ScannerType.DAST, ScannerType.IAC])
def test_factory_rejects_unsupported_scanner_types(scanner_type: ScannerType) -> None:
    with pytest.raises(UnsupportedScannerTypeError, match=scanner_type.value):
        create_scan_execution(MagicMock(), MagicMock(), SimpleNamespace(), scanner_type)


def test_factory_module_never_exposes_legacy_docker_execution() -> None:
    import orchestrator.infrastructure.container.scan_execution_factory as factory_module

    assert not hasattr(factory_module, "LegacyDockerExecution")
