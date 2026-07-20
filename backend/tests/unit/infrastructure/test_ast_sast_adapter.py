"""`AstSastAdapter` — argv builder + non-JSON-prefixed-stdout parser +
per-finding severity map + path normalization (Module 11 PR1, tasks 2.1-2.5).

`AstSastAdapter.scan()` proves the single-call `ContainerRunnerPort.run()`
shape (network-disabled, read-only, no `tmp_exec`) via `FakeContainerRunner`
— no real Docker socket needed here; the live proof lives in
`tests/integration/test_ast_sast_adapter_live.py` (PR2). `.parse()` is a pure
method: `timed_out=True` -> `SastFailedError`; stdout with no `{` character
-> `SastFailedError`; malformed JSON after slicing from the first `{` ->
`SastFailedError`; valid JSON (possibly behind a preamble) -> parsed
`Finding`s (possibly zero) with severity translated from Spanish and
`file_path` stripped of its container mount-path prefix.
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.ast_sast_adapter import (
    _SAST_ARGV,
    _TARGET_DIR,
    AstSastAdapter,
    SastFailedError,
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


def _adapter(runner: FakeContainerRunner | None = None) -> AstSastAdapter:
    """An `AstSastAdapter` used mostly for `.parse()` — no container calls,
    so a fresh unscripted `FakeContainerRunner` is fine unless the test
    scripts a specific `.scan()` result."""
    return AstSastAdapter(runner=runner or FakeContainerRunner(), settings=_settings())


def _json_report(findings: list[dict]) -> str:
    return json.dumps(
        {
            "scanned_path": "/checkout/checkout",
            "generated_at": "2026-07-20T00:00:00+00:00",
            "summary": {"total": len(findings), "ALTA": 0, "MEDIA": 0, "BAJA": 0},
            "findings": findings,
        }
    )


# ---------------------------------------------------------------------------
# 2.5 — argv composition / `.scan()` call shape
# ---------------------------------------------------------------------------


def test_sast_argv_is_a_fixed_tuple_never_interpolated_from_repo_content() -> None:
    assert _SAST_ARGV == (
        "python",
        "-m",
        "sast.cli",
        "--path",
        _TARGET_DIR,
        "--format",
        "json",
    )
    assert isinstance(_SAST_ARGV, tuple)


def test_scan_runs_sast_scanner_read_only_network_disabled() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False))
    settings = _settings()
    adapter = AstSastAdapter(runner=fake_runner, settings=settings)

    adapter.scan("scan-abc123")

    assert len(fake_runner.calls) == 1
    call = fake_runner.calls[0]
    assert call.command == list(_SAST_ARGV)
    assert call.image == settings.scan_sast_image
    assert call.volume_name == "scan-abc123"
    assert call.mount_path == "/checkout"
    assert call.read_only_mount is True
    assert call.network_disabled is True
    assert call.timeout_seconds == settings.scan_timeout_seconds
    assert call.limits.memory_mb == settings.scan_memory_limit_mb
    assert call.limits.pids_limit == settings.scan_pids_limit
    # No subprocess/venv bootstrapping needed (unlike pip-audit D7b) — the
    # default strict `noexec` posture is fine.
    assert call.tmp_exec is False


# ---------------------------------------------------------------------------
# 2.1 — non-JSON-prefixed stdout parsing (D2)
# ---------------------------------------------------------------------------


def test_parse_extracts_json_from_first_brace_behind_a_preamble() -> None:
    preamble = "Analizando: /checkout/checkout ...\nHallazgos: 0 (Alta=0, Media=0, Baja=0)\n"
    result = RunResult(exit_code=0, stdout=preamble + _json_report([]), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_raises_sast_failed_error_when_no_brace_present() -> None:
    result = RunResult(
        exit_code=1, stdout="Analizando: /checkout/checkout ...\n", stderr="crash", timed_out=False
    )

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SastFailedError as exc:
        assert "crash" in str(exc)
    else:
        raise AssertionError("expected SastFailedError when stdout has no '{' character")


def test_parse_raises_sast_failed_error_on_malformed_json_after_slicing() -> None:
    result = RunResult(
        exit_code=1, stdout="Analizando: ...\n{not valid json", stderr="", timed_out=False
    )

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SastFailedError:
        pass
    else:
        raise AssertionError("expected SastFailedError on malformed JSON")


def test_parse_raises_sast_failed_error_when_timed_out_even_with_exit_code_0() -> None:
    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=True)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except SastFailedError:
        pass
    else:
        raise AssertionError("expected SastFailedError when the run timed out")


# ---------------------------------------------------------------------------
# Zero-findings success contract
# ---------------------------------------------------------------------------


def test_parse_empty_findings_list_returns_no_findings_not_an_error() -> None:
    result = RunResult(exit_code=0, stdout=_json_report([]), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


# ---------------------------------------------------------------------------
# 2.2 — severity mapping + safe fallback (D3)
# ---------------------------------------------------------------------------


def test_parse_maps_alta_media_baja_to_high_medium_low() -> None:
    report = _json_report(
        [
            {
                "file": "/checkout/checkout/app/a.py",
                "line": 1,
                "severity": "ALTA",
                "rule_id": "SAST-001",
                "title": "high finding",
                "description": "desc-high",
                "remediation": "fix-high",
            },
            {
                "file": "/checkout/checkout/app/b.py",
                "line": 2,
                "severity": "MEDIA",
                "rule_id": "SAST-002",
                "title": "medium finding",
                "description": "desc-medium",
                "remediation": "fix-medium",
            },
            {
                "file": "/checkout/checkout/app/c.py",
                "line": 3,
                "severity": "BAJA",
                "rule_id": "SAST-003",
                "title": "low finding",
                "description": "desc-low",
                "remediation": "fix-low",
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    by_rule = {f.rule_id: f for f in findings}
    assert len(findings) == 3
    assert by_rule["SAST-001"].severity == FindingSeverity.HIGH
    assert by_rule["SAST-002"].severity == FindingSeverity.MEDIUM
    assert by_rule["SAST-003"].severity == FindingSeverity.LOW


def test_parse_unknown_severity_falls_back_to_medium_and_does_not_fail_scan() -> None:
    report = _json_report(
        [
            {
                "file": "/checkout/checkout/app/a.py",
                "line": 1,
                "severity": "CRITICA",  # not in {ALTA, MEDIA, BAJA}
                "rule_id": "SAST-999",
                "title": "unknown severity finding",
                "description": "desc",
                "remediation": "fix",
            },
            {
                "file": "/checkout/checkout/app/b.py",
                "line": 2,
                "severity": "ALTA",
                "rule_id": "SAST-001",
                "title": "known finding",
                "description": "desc",
                "remediation": "fix",
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    by_rule = {f.rule_id: f for f in findings}
    assert len(findings) == 2
    assert by_rule["SAST-999"].severity == FindingSeverity.MEDIUM
    assert by_rule["SAST-001"].severity == FindingSeverity.HIGH


# ---------------------------------------------------------------------------
# 2.3 — path normalization (D4)
# ---------------------------------------------------------------------------


def test_parse_strips_checkout_checkout_prefix_from_file_path() -> None:
    report = _json_report(
        [
            {
                "file": "/checkout/checkout/app/routes/auth.py",
                "line": 43,
                "severity": "ALTA",
                "rule_id": "SAST-020",
                "title": "hardcoded secret",
                "description": "desc",
                "remediation": "fix",
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    assert findings[0].file_path == "app/routes/auth.py"
    assert "/checkout/checkout" not in findings[0].file_path


# ---------------------------------------------------------------------------
# 2.4 — fingerprint stability
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_across_two_parses_of_the_same_finding() -> None:
    report = _json_report(
        [
            {
                "file": "/checkout/checkout/app/routes/auth.py",
                "line": 43,
                "severity": "ALTA",
                "rule_id": "SAST-020",
                "title": "hardcoded secret",
                "description": "desc",
                "remediation": "fix",
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
                "file": "/checkout/checkout/app/a.py",
                "line": 1,
                "severity": "ALTA",
                "rule_id": "SAST-001",
                "title": "finding a",
                "description": "desc",
                "remediation": "fix",
            },
            {
                "file": "/checkout/checkout/app/a.py",
                "line": 2,
                "severity": "ALTA",
                "rule_id": "SAST-001",
                "title": "finding b, different line",
                "description": "desc",
                "remediation": "fix",
            },
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert findings[0].fingerprint != findings[1].fingerprint


# ---------------------------------------------------------------------------
# Field mapping (rule_id/title/line_number/raw_evidence/snippet)
# ---------------------------------------------------------------------------


def test_parse_maps_all_finding_fields() -> None:
    report = _json_report(
        [
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
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scan_task_id == _SCAN_TASK_ID
    assert finding.rule_id == "SAST-020"
    assert finding.title == "Hardcoded secret key"
    assert finding.line_number == 43
    assert finding.file_path == "app/routes/auth.py"
    assert finding.raw_evidence is not None
    assert finding.raw_evidence["description"] == "A secret key is hardcoded in source."
    assert finding.raw_evidence["remediation"] == "Move the secret to an environment variable."
    assert finding.snippet == "A secret key is hardcoded in source."


# ---------------------------------------------------------------------------
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_ast_sast_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_ast_sast_adapter_supports_sast_but_not_secrets_or_sca() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SAST) is True
    assert adapter.supports(ScannerType.SECRETS) is False
    assert adapter.supports(ScannerType.SCA) is False
