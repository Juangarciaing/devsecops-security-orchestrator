"""`SemgrepAdapter` — argv builder + pure-JSON parser + per-finding severity
map + path normalization (Module 11 PR2, tasks 3.1-3.7).

`SemgrepAdapter.scan()` proves the single-call `ContainerRunnerPort.run()`
shape (network-disabled, read-only, no `tmp_exec`) via `FakeContainerRunner`
— no real Docker socket needed here; the live proof lives in
`tests/integration/test_semgrep_adapter_live.py` (PR3). `.parse()` is a pure
method: `timed_out=True` -> `SemgrepFailedError`; empty/malformed JSON /
missing `results` key -> `SemgrepFailedError`; valid JSON -> parsed
`Finding`s (possibly zero), mirroring `PipAuditAdapter`'s D4 parse-driven,
exit-code-agnostic contract (confirmed against the real, installed
`semgrep==1.170.0` CLI: `--quiet --json` emits pure JSON with no preamble,
and exit code stays 0 even with findings present).
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.semgrep_adapter import (
    _SEMGREP_ARGV,
    _TARGET_DIR,
    SemgrepAdapter,
    SemgrepFailedError,
)
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


def _adapter(runner: FakeContainerRunner | None = None) -> SemgrepAdapter:
    """A `SemgrepAdapter` used mostly for `.parse()` — no container calls,
    so a fresh unscripted `FakeContainerRunner` is fine unless the test
    scripts a specific `.scan()` result."""
    return SemgrepAdapter(runner=runner or FakeContainerRunner(), settings=_settings())


def _json_report(results: list[dict]) -> str:
    return json.dumps({"version": "1.170.0", "results": results, "errors": []})


# ---------------------------------------------------------------------------
# 3.5 — argv composition / `.scan()` call shape
# ---------------------------------------------------------------------------


def test_semgrep_argv_is_a_fixed_tuple_never_interpolated_from_repo_content() -> None:
    assert _SEMGREP_ARGV == (
        "semgrep",
        "scan",
        "--config",
        "/rules",
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        _TARGET_DIR,
    )
    assert isinstance(_SEMGREP_ARGV, tuple)


def test_scan_runs_semgrep_read_only_network_disabled() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False))
    settings = _settings()
    adapter = SemgrepAdapter(runner=fake_runner, settings=settings)

    adapter.scan("scan-abc123")

    assert len(fake_runner.calls) == 1
    call = fake_runner.calls[0]
    assert call.command == list(_SEMGREP_ARGV)
    assert call.image == settings.scan_semgrep_image
    assert call.volume_name == "scan-abc123"
    assert call.mount_path == "/checkout"
    assert call.read_only_mount is True
    assert call.network_disabled is True
    assert call.timeout_seconds == settings.scan_timeout_seconds
    assert call.limits.memory_mb == settings.scan_memory_limit_mb
    assert call.limits.pids_limit == settings.scan_pids_limit
    # Confirmed against a real hardened-container smoke test (PR2): semgrep
    # needs no subprocess/venv bootstrapping under /tmp, unlike pip-audit
    # (D7b) — the default strict `noexec` posture is fine.
    assert call.tmp_exec is False


# ---------------------------------------------------------------------------
# 3.1 — pure-JSON stdout parsing (D6)
# ---------------------------------------------------------------------------


def test_parse_valid_results_array_returns_findings() -> None:
    report = _json_report(
        [
            {
                "check_id": "python.lang.security.audit.subprocess-shell-true",
                "path": f"{_TARGET_DIR}/app/a.py",
                "start": {"line": 5, "col": 1},
                "end": {"line": 5, "col": 10},
                "extra": {"severity": "ERROR", "message": "dangerous shell=True"},
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scan_task_id == _SCAN_TASK_ID
    assert finding.rule_id == "python.lang.security.audit.subprocess-shell-true"
    assert finding.title == "python.lang.security.audit.subprocess-shell-true"
    assert finding.line_number == 5
    assert finding.file_path == "app/a.py"
    assert finding.severity == FindingSeverity.HIGH
    assert finding.snippet == "dangerous shell=True"
    assert finding.raw_evidence is not None
    assert finding.raw_evidence["message"] == "dangerous shell=True"
    assert finding.fingerprint


def test_parse_empty_results_returns_no_findings_not_an_error() -> None:
    result = RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_exit_code_1_with_valid_json_is_success_not_error() -> None:
    """Confirmed against the real installed CLI: semgrep's exit code is
    IGNORED (D6) — `parse()` is driven entirely by JSON `results[]`
    presence, mirroring pip-audit's D4 parse-driven contract."""
    report = _json_report(
        [
            {
                "check_id": "rule-a",
                "path": f"{_TARGET_DIR}/a.py",
                "start": {"line": 1, "col": 1},
                "end": {"line": 1, "col": 2},
                "extra": {"severity": "WARNING", "message": "msg"},
            }
        ]
    )
    result = RunResult(exit_code=1, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1


def test_parse_raises_semgrep_failed_error_when_timed_out_even_with_exit_code_0() -> None:
    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=True)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SemgrepFailedError:
        pass
    else:
        raise AssertionError("expected SemgrepFailedError when the run timed out")


def test_parse_empty_stdout_raises_semgrep_failed_error() -> None:
    result = RunResult(exit_code=2, stdout="", stderr="semgrep crashed", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SemgrepFailedError as exc:
        assert "semgrep crashed" in str(exc)
    else:
        raise AssertionError("expected SemgrepFailedError on empty stdout")


def test_parse_malformed_json_raises_semgrep_failed_error() -> None:
    result = RunResult(exit_code=2, stdout="{not valid json", stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SemgrepFailedError:
        pass
    else:
        raise AssertionError("expected SemgrepFailedError on malformed JSON")


def test_parse_json_without_results_key_raises_semgrep_failed_error() -> None:
    result = RunResult(exit_code=2, stdout='{"unexpected": true}', stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SemgrepFailedError:
        pass
    else:
        raise AssertionError("expected SemgrepFailedError when 'results' key is missing")


# ---------------------------------------------------------------------------
# 3.2 — severity mapping + safe fallback (D7)
# ---------------------------------------------------------------------------


def test_parse_maps_error_warning_info_to_high_medium_low() -> None:
    report = _json_report(
        [
            {
                "check_id": "rule-high",
                "path": f"{_TARGET_DIR}/a.py",
                "start": {"line": 1, "col": 1},
                "end": {"line": 1, "col": 2},
                "extra": {"severity": "ERROR", "message": "high"},
            },
            {
                "check_id": "rule-medium",
                "path": f"{_TARGET_DIR}/b.py",
                "start": {"line": 2, "col": 1},
                "end": {"line": 2, "col": 2},
                "extra": {"severity": "WARNING", "message": "medium"},
            },
            {
                "check_id": "rule-low",
                "path": f"{_TARGET_DIR}/c.py",
                "start": {"line": 3, "col": 1},
                "end": {"line": 3, "col": 2},
                "extra": {"severity": "INFO", "message": "low"},
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    by_rule = {f.rule_id: f for f in findings}
    assert len(findings) == 3
    assert by_rule["rule-high"].severity == FindingSeverity.HIGH
    assert by_rule["rule-medium"].severity == FindingSeverity.MEDIUM
    assert by_rule["rule-low"].severity == FindingSeverity.LOW


def test_parse_unknown_severity_falls_back_to_medium_and_does_not_fail_scan() -> None:
    report = _json_report(
        [
            {
                "check_id": "rule-unknown",
                "path": f"{_TARGET_DIR}/a.py",
                "start": {"line": 1, "col": 1},
                "end": {"line": 1, "col": 2},
                "extra": {"severity": "CRITICAL", "message": "not in {ERROR, WARNING, INFO}"},
            },
            {
                "check_id": "rule-known",
                "path": f"{_TARGET_DIR}/b.py",
                "start": {"line": 2, "col": 1},
                "end": {"line": 2, "col": 2},
                "extra": {"severity": "ERROR", "message": "known"},
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    by_rule = {f.rule_id: f for f in findings}
    assert len(findings) == 2
    assert by_rule["rule-unknown"].severity == FindingSeverity.MEDIUM
    assert by_rule["rule-known"].severity == FindingSeverity.HIGH


# ---------------------------------------------------------------------------
# 3.3 — path normalization (D9)
# ---------------------------------------------------------------------------


def test_parse_strips_checkout_checkout_prefix_from_file_path() -> None:
    report = _json_report(
        [
            {
                "check_id": "rule-x",
                "path": f"{_TARGET_DIR}/app/routes/auth.py",
                "start": {"line": 43, "col": 1},
                "end": {"line": 43, "col": 2},
                "extra": {"severity": "ERROR", "message": "hardcoded secret"},
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    assert findings[0].file_path == "app/routes/auth.py"
    assert _TARGET_DIR not in findings[0].file_path


# ---------------------------------------------------------------------------
# 3.4 — fingerprint stability
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_across_two_parses_of_the_same_finding() -> None:
    report = _json_report(
        [
            {
                "check_id": "rule-x",
                "path": f"{_TARGET_DIR}/app/routes/auth.py",
                "start": {"line": 43, "col": 1},
                "end": {"line": 43, "col": 2},
                "extra": {"severity": "ERROR", "message": "hardcoded secret"},
            }
        ]
    )
    result_a = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)
    result_b = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings_a = _adapter().parse(result_a, _SCAN_TASK_ID)
    findings_b = _adapter().parse(result_b, uuid.uuid4())

    assert findings_a[0].fingerprint == findings_b[0].fingerprint
    assert findings_a[0].fingerprint != ""


def test_fingerprint_differs_for_different_rule_file_or_line() -> None:
    report = _json_report(
        [
            {
                "check_id": "rule-x",
                "path": f"{_TARGET_DIR}/a.py",
                "start": {"line": 1, "col": 1},
                "end": {"line": 1, "col": 2},
                "extra": {"severity": "ERROR", "message": "finding a"},
            },
            {
                "check_id": "rule-x",
                "path": f"{_TARGET_DIR}/a.py",
                "start": {"line": 2, "col": 1},
                "end": {"line": 2, "col": 2},
                "extra": {"severity": "ERROR", "message": "finding b, different line"},
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert findings[0].fingerprint != findings[1].fingerprint


# ---------------------------------------------------------------------------
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_semgrep_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_semgrep_adapter_supports_semgrep_but_not_sast_secrets_or_sca() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SEMGREP) is True
    assert adapter.supports(ScannerType.SAST) is False
    assert adapter.supports(ScannerType.SECRETS) is False
    assert adapter.supports(ScannerType.SCA) is False
