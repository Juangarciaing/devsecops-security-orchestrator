"""`ScanExecutionPort.execute()` gains an additive, defaulted `credential`
kwarg (PR5, task 5.11) — no existing caller needs to change when it omits
the parameter (`None` reproduces today's public-repo behavior)."""

from __future__ import annotations

import inspect

from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort


def test_execute_signature_appends_a_defaulted_credential_param_last() -> None:
    params = list(inspect.signature(ScanExecutionPort.execute).parameters.values())
    assert params[-1].name == "credential"
    assert params[-1].default is None
