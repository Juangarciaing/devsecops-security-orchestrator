"""`SemgrepAdapter` — argv constant + pure-JSON parser + per-finding severity
map + path normalization (Module 11 PR2, tasks 3.1-3.7).

`.parse()` is a pure method: `timed_out=True` -> `SemgrepFailedError`;
empty/malformed JSON / missing `results` key -> `SemgrepFailedError`; valid
JSON -> parsed `Finding`s (possibly zero), mirroring `PipAuditAdapter`'s D4
parse-driven, exit-code-agnostic contract (confirmed against the real,
installed `semgrep==1.170.0` CLI: `--quiet --json` emits pure JSON with no
preamble, and exit code stays 0 even with findings present). The
single-call container-invocation shape is covered by
`tests/integration/test_semgrep_adapter_live.py` (real Docker); the compat
`scan(volume_name)` shape test was removed in Module 13c PR5c-1. Clean-run,
malformed-input, and finding-redaction parser cases are now owned solely by
`test_semgrep_parser_contract.py` (Module 13c PR5c-2) — this file keeps
only cases with no parser-contract analog.
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


def _adapter() -> SemgrepAdapter:
    """A `SemgrepAdapter` used only for `.parse()` in these tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return SemgrepAdapter(runner=FakeContainerRunner(), settings=_settings())


def _json_report(results: list[dict]) -> str:
    return json.dumps({"version": "1.170.0", "results": results, "errors": []})


# ---------------------------------------------------------------------------
# 3.5 — argv composition (fixed, never interpolated from repo content)
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
