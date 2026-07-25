"""`AstSastAdapter.parse()` — compact parser/security contract (Module 13c
PR5a, decision `pr5a-contract-strategy`).

Independent, parametrized coverage of the parser behavior that must survive
`LegacyDockerExecution` removal (PR5b) unchanged: clean-run parsing,
malformed/failure handling, and `Finding.REDACTION_SENSITIVE_FIELDS`
population. This is deliberate short-lived duplication with
`test_ast_sast_adapter.py` — removed later in PR5c per an explicit deletion
manifest, not now.
"""

from __future__ import annotations

import json
import uuid

import pytest

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.ast_sast_adapter import AstSastAdapter, SastFailedError
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()


def _adapter() -> AstSastAdapter:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    return AstSastAdapter(runner=FakeContainerRunner(), settings=settings)


def _json_report(findings: list[dict]) -> str:
    return json.dumps({"findings": findings})


# ---------------------------------------------------------------------------
# Clean-run / findings parsing contract
# ---------------------------------------------------------------------------


def test_clean_run_empty_findings_parses_to_zero_findings() -> None:
    result = RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False)

    assert _adapter().parse(result, _SCAN_TASK_ID) == []


def test_findings_behind_a_preamble_parse_to_one_finding_each() -> None:
    preamble = "Analizando: /checkout/checkout ...\nHallazgos: 2\n"
    entries = [
        {"file": "/checkout/checkout/a.py", "line": 1, "severity": "ALTA", "rule_id": "SAST-001"},
        {"file": "/checkout/checkout/b.py", "line": 2, "severity": "BAJA", "rule_id": "SAST-002"},
    ]
    result = RunResult(
        exit_code=0, stdout=preamble + _json_report(entries), stderr="", timed_out=False
    )

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert {f.rule_id for f in findings} == {"SAST-001", "SAST-002"}


# ---------------------------------------------------------------------------
# Malformed-input / failure handling contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            RunResult(exit_code=1, stdout="Analizando: ...\n", stderr="crash", timed_out=False),
            id="no-brace-in-stdout",
        ),
        pytest.param(
            RunResult(exit_code=1, stdout="pre\n{not valid json", stderr="", timed_out=False),
            id="malformed-json-after-slice",
        ),
        pytest.param(RunResult(exit_code=0, stdout="", stderr="", timed_out=True), id="timed-out"),
    ],
)
def test_malformed_or_failed_runs_raise_sast_failed_error(result: RunResult) -> None:
    with pytest.raises(SastFailedError):
        _adapter().parse(result, _SCAN_TASK_ID)


# ---------------------------------------------------------------------------
# Finding-field shape / REDACTION_SENSITIVE_FIELDS contract
# ---------------------------------------------------------------------------


def test_parsed_finding_populates_every_redaction_sensitive_field() -> None:
    entries = [
        {
            "file": "/checkout/checkout/app/routes/auth.py",
            "line": 43,
            "severity": "ALTA",
            "rule_id": "SAST-020",
            "title": "Hardcoded secret key",
            "description": "A secret key is hardcoded in source.",
            "remediation": "Move the secret to an environment variable.",
        }
    ]
    result = RunResult(exit_code=0, stdout=_json_report(entries), stderr="", timed_out=False)

    finding = _adapter().parse(result, _SCAN_TASK_ID)[0]

    for field in Finding.REDACTION_SENSITIVE_FIELDS:
        assert getattr(finding, field), f"expected {field!r} to be populated"
    assert finding.file_path == "app/routes/auth.py"
    assert "/checkout/checkout" not in finding.file_path
