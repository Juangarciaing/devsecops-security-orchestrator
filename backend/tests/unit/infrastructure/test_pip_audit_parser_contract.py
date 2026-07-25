"""`PipAuditAdapter.parse()` — compact parser/security contract (Module 13c
PR5a, decision `pr5a-contract-strategy`).

Independent, parametrized coverage of the parser behavior that must survive
`LegacyDockerExecution` removal (PR5b) unchanged: clean-run parsing,
malformed/failure handling, and `Finding.REDACTION_SENSITIVE_FIELDS`
population. This is deliberate short-lived duplication with
`test_pip_audit_adapter.py` — removed later in PR5c per an explicit deletion
manifest, not now.
"""

from __future__ import annotations

import json
import uuid

import pytest

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.pip_audit_adapter import (
    PipAuditAdapter,
    PipAuditFailedError,
)
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()


def _adapter() -> PipAuditAdapter:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    return PipAuditAdapter(runner=FakeContainerRunner(), settings=settings)


# ---------------------------------------------------------------------------
# Clean-run / findings parsing contract
# ---------------------------------------------------------------------------


def test_clean_run_empty_dependencies_parses_to_zero_findings() -> None:
    result = RunResult(exit_code=0, stdout='{"dependencies": []}', stderr="", timed_out=False)

    assert _adapter().parse(result, _SCAN_TASK_ID) == []


def test_dependencies_with_vulns_parse_to_one_finding_each() -> None:
    report = {
        "dependencies": [
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "vulns": [{"id": "GHSA-aaaa", "description": "d-a", "fix_versions": []}],
            },
            {
                "name": "pkg-b",
                "version": "2.0.0",
                "vulns": [{"id": "GHSA-bbbb", "description": "d-b", "fix_versions": []}],
            },
        ]
    }
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert {f.rule_id for f in findings} == {"GHSA-aaaa", "GHSA-bbbb"}


# ---------------------------------------------------------------------------
# Malformed-input / failure handling contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            RunResult(exit_code=1, stdout="", stderr="crashed", timed_out=False), id="empty-stdout"
        ),
        pytest.param(
            RunResult(exit_code=1, stdout="{not valid json", stderr="", timed_out=False),
            id="malformed-json",
        ),
        pytest.param(
            RunResult(exit_code=1, stdout='{"unexpected": true}', stderr="", timed_out=False),
            id="missing-dependencies-key",
        ),
        pytest.param(RunResult(exit_code=0, stdout="", stderr="", timed_out=True), id="timed-out"),
    ],
)
def test_malformed_or_failed_runs_raise_pip_audit_failed_error(result: RunResult) -> None:
    with pytest.raises(PipAuditFailedError):
        _adapter().parse(result, _SCAN_TASK_ID)


# ---------------------------------------------------------------------------
# Finding-field shape / REDACTION_SENSITIVE_FIELDS contract
# ---------------------------------------------------------------------------


def test_parsed_finding_populates_every_redaction_sensitive_field() -> None:
    report = {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.19.0",
                "vulns": [
                    {
                        "id": "PYSEC-2018-28",
                        "description": "Requests before 2.20.0 exposes proxy credentials.",
                        "fix_versions": ["2.20.0"],
                    }
                ],
            }
        ]
    }
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    finding = _adapter().parse(result, _SCAN_TASK_ID)[0]

    # pip-audit has no per-vuln line concept (D3-adjacent adapter contract):
    # `line_number` stays `None` while the other three sensitive fields are
    # always populated from the vuln report.
    for field in Finding.REDACTION_SENSITIVE_FIELDS - {"line_number"}:
        assert getattr(finding, field), f"expected {field!r} to be populated"
    assert finding.line_number is None
    assert finding.raw_evidence is not None
    assert "proxy credentials" in finding.raw_evidence["description"]
