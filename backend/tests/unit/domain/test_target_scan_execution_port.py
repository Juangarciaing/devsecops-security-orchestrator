"""`TargetScanExecutionPort` — DAST-only sibling of `ScanExecutionPort`
(dast-scanner design D5, PR5b task 5.13).

`ScanExecutionPort.execute(clone_url, ref, ...)` hardcodes the checkout unit
of work every repository-subject scanner shares; a DAST scan against an
arbitrary `target_url` has no checkout/commit-sha concept at all, so it gets
its own narrow port rather than overloading `clone_url` with a URL that was
never meant to be cloned (design D5)."""

from __future__ import annotations

import inspect
from abc import ABC

from orchestrator.domain.ports.target_scan_execution_port import (
    TargetScanExecutionPort,
    TargetScanExecutionResult,
)


def test_target_scan_execution_port_is_an_abc() -> None:
    assert issubclass(TargetScanExecutionPort, ABC)


def test_target_scan_execution_port_execute_is_declared_sync_not_async() -> None:
    """Mirrors `ScanExecutionPort.execute` (Module 6 D3): container
    orchestration is blocking I/O, invoked outside any async DB session."""
    assert "execute" in TargetScanExecutionPort.__abstractmethods__
    assert not inspect.iscoroutinefunction(TargetScanExecutionPort.execute)


def test_target_scan_execution_port_execute_signature_has_no_checkout_concept() -> None:
    """Unlike `ScanExecutionPort.execute`, there is no `clone_url`/`ref`/
    `credential` — a target scan has no checkout unit of work at all."""
    params = list(inspect.signature(TargetScanExecutionPort.execute).parameters.values())
    names = [p.name for p in params if p.name != "self"]
    assert names == ["target_url", "scan_task_id", "scanner_type"]
    for name in ("clone_url", "ref", "credential"):
        assert name not in names


def test_target_scan_execution_result_is_frozen_and_slotted() -> None:
    result = TargetScanExecutionResult(findings=[])
    assert result.findings == []
    assert not hasattr(result, "__dict__")  # slots=True
