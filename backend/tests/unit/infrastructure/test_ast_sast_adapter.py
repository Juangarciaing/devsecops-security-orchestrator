"""`AstSastAdapter` — argv constant + non-JSON-prefixed-stdout parser +
per-finding severity map + path normalization (Module 11 PR1, tasks 2.1-2.5).

`.parse()` is a pure method: `timed_out=True` -> `SastFailedError`; stdout
with no `{` character -> `SastFailedError`; malformed JSON after slicing
from the first `{` -> `SastFailedError`; valid JSON (possibly behind a
preamble) -> parsed `Finding`s (possibly zero) with severity translated from
Spanish and `file_path` stripped of its container mount-path prefix. The
single-call container-invocation shape is covered by
`tests/integration/test_ast_sast_adapter_live.py` (real Docker); the compat
`scan(volume_name)` shape test was removed in Module 13c PR5c-1. Clean-run,
malformed-input, and finding-redaction parser cases are now owned solely by
`test_ast_sast_parser_contract.py` (Module 13c PR5c-2) — this file keeps
only cases with no parser-contract analog.
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


def _adapter() -> AstSastAdapter:
    """An `AstSastAdapter` used only for `.parse()` in these tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return AstSastAdapter(runner=FakeContainerRunner(), settings=_settings())


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
# 2.5 — argv composition (fixed, never interpolated from repo content)
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
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_ast_sast_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_ast_sast_adapter_supports_sast_but_not_secrets_or_sca() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SAST) is True
    assert adapter.supports(ScannerType.SECRETS) is False
    assert adapter.supports(ScannerType.SCA) is False
