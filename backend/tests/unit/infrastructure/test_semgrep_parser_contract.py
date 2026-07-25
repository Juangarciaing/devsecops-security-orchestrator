"""`SemgrepAdapter.parse()` — compact parser/security contract (Module 13c
PR5a, decision `pr5a-contract-strategy`).

Independent, parametrized coverage of the parser behavior that must survive
`LegacyDockerExecution` removal (PR5b) unchanged: clean-run/findings
parsing, malformed/failure handling, and `Finding.REDACTION_SENSITIVE_FIELDS`
population. This is deliberate short-lived duplication with
`test_semgrep_adapter.py` — removed later in PR5c per an explicit deletion
manifest, not now.
"""

from __future__ import annotations

import json
import uuid

import pytest

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import FindingSeverity
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.semgrep_adapter import SemgrepAdapter, SemgrepFailedError
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()


def _adapter() -> SemgrepAdapter:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    return SemgrepAdapter(runner=FakeContainerRunner(), settings=settings)


def _json_report(results: list[dict]) -> str:
    return json.dumps({"version": "1.170.0", "results": results, "errors": []})


# ---------------------------------------------------------------------------
# Clean-run / findings parsing contract
# ---------------------------------------------------------------------------


def test_clean_run_empty_results_parses_to_zero_findings() -> None:
    result = RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False)

    assert _adapter().parse(result, _SCAN_TASK_ID) == []


def test_findings_in_results_parse_to_one_finding_each() -> None:
    entries = [
        {
            "check_id": "rule-a",
            "path": "/checkout/checkout/a.py",
            "start": {"line": 1, "col": 1},
            "end": {"line": 1, "col": 2},
            "extra": {"severity": "ERROR", "message": "msg-a"},
        },
        {
            "check_id": "rule-b",
            "path": "/checkout/checkout/b.py",
            "start": {"line": 2, "col": 1},
            "end": {"line": 2, "col": 2},
            "extra": {"severity": "WARNING", "message": "msg-b"},
        },
    ]
    result = RunResult(exit_code=0, stdout=_json_report(entries), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert {f.rule_id for f in findings} == {"rule-a", "rule-b"}


def test_exit_code_is_ignored_valid_json_with_findings_is_success() -> None:
    """D6: semgrep's own exit code is not authoritative — a nonzero exit with
    valid `results[]` is still a successful parse, not a failure."""
    entries = [
        {
            "check_id": "rule-x",
            "path": "/checkout/checkout/a.py",
            "start": {"line": 1, "col": 1},
            "end": {"line": 1, "col": 2},
            "extra": {"severity": "ERROR", "message": "msg"},
        }
    ]
    result = RunResult(exit_code=1, stdout=_json_report(entries), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1


# ---------------------------------------------------------------------------
# Malformed-input / failure handling contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            RunResult(exit_code=2, stdout="", stderr="crashed", timed_out=False),
            id="empty-stdout",
        ),
        pytest.param(
            RunResult(exit_code=2, stdout="{not valid json", stderr="", timed_out=False),
            id="malformed-json",
        ),
        pytest.param(
            RunResult(exit_code=2, stdout='{"unexpected": true}', stderr="", timed_out=False),
            id="missing-results-key",
        ),
        pytest.param(RunResult(exit_code=0, stdout="", stderr="", timed_out=True), id="timed-out"),
    ],
)
def test_malformed_or_failed_runs_raise_semgrep_failed_error(result: RunResult) -> None:
    with pytest.raises(SemgrepFailedError):
        _adapter().parse(result, _SCAN_TASK_ID)


# ---------------------------------------------------------------------------
# Severity-fallback / fail-closed contract (D7)
# ---------------------------------------------------------------------------


def test_unknown_severity_falls_back_to_medium_not_a_parse_failure() -> None:
    """D7: an unrecognized `extra.severity` value must not silently drop the
    finding or fail the whole scan — it degrades to MEDIUM, staying
    fail-closed on findings rather than fail-open on unrecognized output."""
    entries = [
        {
            "check_id": "rule-unknown",
            "path": "/checkout/checkout/a.py",
            "start": {"line": 1, "col": 1},
            "end": {"line": 1, "col": 2},
            "extra": {"severity": "CRITICAL", "message": "not in {ERROR, WARNING, INFO}"},
        }
    ]
    result = RunResult(exit_code=0, stdout=_json_report(entries), stderr="", timed_out=False)

    finding = _adapter().parse(result, _SCAN_TASK_ID)[0]

    assert finding.severity == FindingSeverity.MEDIUM


# ---------------------------------------------------------------------------
# Finding-field shape / REDACTION_SENSITIVE_FIELDS contract
# ---------------------------------------------------------------------------


def test_parsed_finding_populates_every_redaction_sensitive_field() -> None:
    entries = [
        {
            "check_id": "python.lang.security.audit.hardcoded-secret",
            "path": "/checkout/checkout/app/routes/auth.py",
            "start": {"line": 43, "col": 1},
            "end": {"line": 43, "col": 2},
            "extra": {"severity": "ERROR", "message": "Hardcoded secret key detected"},
        }
    ]
    result = RunResult(exit_code=0, stdout=_json_report(entries), stderr="", timed_out=False)

    finding = _adapter().parse(result, _SCAN_TASK_ID)[0]

    for field in Finding.REDACTION_SENSITIVE_FIELDS:
        assert getattr(finding, field), f"expected {field!r} to be populated"
    assert finding.file_path == "app/routes/auth.py"
    assert "/checkout/checkout" not in finding.file_path
    assert finding.raw_evidence is not None
    assert "Hardcoded secret" in finding.raw_evidence["message"]
