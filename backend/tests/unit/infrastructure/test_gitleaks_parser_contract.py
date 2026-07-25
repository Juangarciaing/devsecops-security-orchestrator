"""`GitleaksAdapter.parse()` — compact parser/security contract (Module 13c
PR5a, decision `pr5a-contract-strategy`).

Independent, parametrized coverage of the parser behavior that must survive
`LegacyDockerExecution` removal (PR5b) unchanged: clean-run parsing,
malformed/failure handling, and `Finding.REDACTION_SENSITIVE_FIELDS`
population. This is deliberate short-lived duplication with
`test_gitleaks_adapter.py` — removed later in PR5c per an explicit deletion
manifest, not now.
"""

from __future__ import annotations

import json
import uuid

import pytest

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.gitleaks_adapter import (
    GitleaksAdapter,
    GitleaksFailedError,
)
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()


def _adapter() -> GitleaksAdapter:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    return GitleaksAdapter(runner=FakeContainerRunner(), settings=settings)


# ---------------------------------------------------------------------------
# Clean-run / findings parsing contract
# ---------------------------------------------------------------------------


def test_clean_run_exit_0_parses_to_zero_findings() -> None:
    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)

    assert _adapter().parse(result, _SCAN_TASK_ID) == []


def test_leaks_found_exit_2_parses_every_entry_to_a_finding() -> None:
    report = [
        {"RuleID": "aws-access-token", "File": "a.py", "StartLine": 1, "Secret": "s1"},
        {"RuleID": "slack-token", "File": "b.py", "StartLine": 2, "Secret": "s2"},
    ]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert {f.rule_id for f in findings} == {"aws-access-token", "slack-token"}


# ---------------------------------------------------------------------------
# Malformed-input / failure handling contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            RunResult(exit_code=1, stdout="", stderr="fatal", timed_out=False),
            id="nonstandard-exit",
        ),
        pytest.param(
            RunResult(exit_code=2, stdout="{not valid json", stderr="", timed_out=False),
            id="malformed-json",
        ),
        pytest.param(
            RunResult(exit_code=2, stdout='"not-a-list"', stderr="", timed_out=False),
            id="wrong-json-shape",
        ),
        pytest.param(RunResult(exit_code=0, stdout="", stderr="", timed_out=True), id="timed-out"),
    ],
)
def test_malformed_or_failed_runs_raise_gitleaks_failed_error(result: RunResult) -> None:
    with pytest.raises(GitleaksFailedError):
        _adapter().parse(result, _SCAN_TASK_ID)


# ---------------------------------------------------------------------------
# Finding-field shape / REDACTION_SENSITIVE_FIELDS contract
# ---------------------------------------------------------------------------


def test_parsed_finding_populates_every_redaction_sensitive_field() -> None:
    report = [
        {
            "RuleID": "aws-access-token",
            "Description": "AWS Access Key",
            "File": "config.py",
            "StartLine": 12,
            "Secret": "AKIAIOSFODNN7EXAMPLE",
        }
    ]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    finding = _adapter().parse(result, _SCAN_TASK_ID)[0]

    for field in Finding.REDACTION_SENSITIVE_FIELDS:
        assert getattr(finding, field), f"expected {field!r} to be populated"
    assert finding.raw_evidence is not None
    assert finding.raw_evidence["secret"] == "AKIAIOSFODNN7EXAMPLE"
