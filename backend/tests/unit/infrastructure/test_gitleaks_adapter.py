"""`GitleaksAdapter` — argv builder + JSON-to-`Finding` parser (Module 6 PR2,
tasks 2.1-2.3).

`GitleaksAdapter.scan()` proves the exact `ContainerRunnerPort.run()` call
shape via `FakeContainerRunner` (no real Docker socket needed here — that
live proof lives in `tests/integration/test_gitleaks_adapter_live.py`).
`parse()` is a pure function: exit 0 -> no findings, exit 2 + JSON report ->
parsed `Finding`s, anything else (or `timed_out=True`) -> `GitleaksFailedError`
(D4/D5 — never conflate "leaks found" with a genuine tool failure).
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import FindingSeverity
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksAdapter, parse
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


# ---------------------------------------------------------------------------
# 2.1 — argv builder / `.scan()` call shape
# ---------------------------------------------------------------------------


def test_scan_runs_gitleaks_against_the_checkout_subdir_with_hardened_kwargs() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(RunResult(exit_code=0, stdout="", stderr="", timed_out=False))
    settings = _settings()
    adapter = GitleaksAdapter(runner=fake_runner, settings=settings)

    adapter.scan("scan-abc123")

    assert len(fake_runner.calls) == 1
    call = fake_runner.calls[0]
    assert call.command == [
        "dir",
        "/checkout/checkout",
        "--report-format=json",
        "--report-path=/dev/stdout",
        "--exit-code=2",
        "--no-banner",
    ]
    assert call.image == settings.scan_container_image
    assert call.volume_name == "scan-abc123"
    assert call.mount_path == "/checkout"
    assert call.read_only_mount is True
    assert call.network_disabled is True
    assert call.timeout_seconds == settings.scan_timeout_seconds
    assert call.limits.memory_mb == settings.scan_memory_limit_mb
    assert call.limits.pids_limit == settings.scan_pids_limit


def test_scan_returns_the_raw_run_result() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(RunResult(exit_code=2, stdout="[]", stderr="", timed_out=False))
    adapter = GitleaksAdapter(runner=fake_runner, settings=_settings())

    result = adapter.scan("scan-xyz")

    assert result.exit_code == 2
    assert result.stdout == "[]"


# ---------------------------------------------------------------------------
# 2.2 — parse(RunResult)
# ---------------------------------------------------------------------------


def test_parse_exit_0_returns_no_findings() -> None:
    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)

    findings = parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_exit_2_with_one_leak_returns_one_finding_with_all_fields_mapped() -> None:
    report = [
        {
            "RuleID": "aws-access-token",
            "Description": "AWS Access Key",
            "File": "config.py",
            "StartLine": 12,
            "Match": "aws_key = AKIAIOSFODNN7EXAMPLE",
            "Secret": "AKIAIOSFODNN7EXAMPLE",
            "Commit": "deadbeef",
        }
    ]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scan_task_id == _SCAN_TASK_ID
    assert finding.rule_id == "aws-access-token"
    assert finding.title == "AWS Access Key"
    assert finding.severity == FindingSeverity.HIGH
    assert finding.file_path == "config.py"
    assert finding.line_number == 12
    assert finding.snippet == "AKIAIOSFODNN7EXAMPLE"
    assert finding.raw_evidence is not None
    assert finding.raw_evidence["secret"] == "AKIAIOSFODNN7EXAMPLE"
    assert finding.fingerprint


def test_parse_exit_2_with_three_leaks_returns_three_findings_triangulation() -> None:
    report = [
        {
            "RuleID": "generic-api-key",
            "Description": "Generic API Key",
            "File": "a.py",
            "StartLine": 1,
            "Secret": "secret-one",
        },
        {
            "RuleID": "generic-api-key",
            "Description": "Generic API Key",
            "File": "b.py",
            "StartLine": 2,
            "Secret": "secret-two",
        },
        {
            "RuleID": "slack-token",
            "Description": "Slack Token",
            "File": "c.py",
            "StartLine": 3,
            "Secret": "secret-three",
        },
    ]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = parse(result, _SCAN_TASK_ID)

    assert len(findings) == 3
    assert {f.rule_id for f in findings} == {"generic-api-key", "slack-token"}
    # Distinct secrets/files/lines -> distinct fingerprints (dedup key).
    assert len({f.fingerprint for f in findings}) == 3


def test_parse_exit_1_raises_gitleaks_failed_error() -> None:
    from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError

    result = RunResult(exit_code=1, stdout="", stderr="fatal: bad config", timed_out=False)

    try:
        parse(result, _SCAN_TASK_ID)
    except GitleaksFailedError as exc:
        assert "1" in str(exc)
    else:
        raise AssertionError("expected GitleaksFailedError")


def test_parse_other_nonstandard_exit_code_raises_gitleaks_failed_error() -> None:
    from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError

    result = RunResult(exit_code=126, stdout="", stderr="unknown flag", timed_out=False)

    try:
        parse(result, _SCAN_TASK_ID)
    except GitleaksFailedError:
        pass
    else:
        raise AssertionError("expected GitleaksFailedError")


def test_parse_timed_out_raises_gitleaks_failed_error_even_with_exit_code_0() -> None:
    from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError

    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=True)

    try:
        parse(result, _SCAN_TASK_ID)
    except GitleaksFailedError:
        pass
    else:
        raise AssertionError("expected GitleaksFailedError")


def test_parse_malformed_json_on_exit_2_raises_gitleaks_failed_error() -> None:
    from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError

    result = RunResult(exit_code=2, stdout="{not valid json", stderr="", timed_out=False)

    try:
        parse(result, _SCAN_TASK_ID)
    except GitleaksFailedError:
        pass
    else:
        raise AssertionError("expected GitleaksFailedError")


def test_parse_uses_rule_id_as_title_fallback_when_description_missing() -> None:
    report = [{"RuleID": "generic-secret", "File": "x.py", "StartLine": 1, "Secret": "s"}]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = parse(result, _SCAN_TASK_ID)

    assert findings[0].title == "generic-secret"
