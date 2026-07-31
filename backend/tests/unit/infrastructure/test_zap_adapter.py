"""`ZapAdapter` — OWASP ZAP baseline-scan JSON report parser (dast-scanner
PR5a, tasks 5.1/5.9/5.10).

`.parse()` is a pure method: `timed_out=True` -> `ZapFailedError` WITHOUT
attempting to parse `stdout` at all; a well-formed report (`{"site": [...]}`)
-> parsed `Finding`s (possibly zero — zero alerts is a valid, successful
scan); anything that isn't a recognizable ZAP report shape (empty stdout,
malformed JSON, JSON missing the top-level `site` key) -> `ZapFailedError`
(deterministic — mirrors `semgrep_adapter`/`pip_audit_adapter`'s own
missing-key-is-a-genuine-failure precedent, never a silently empty scan).
Exit-code-agnostic throughout: `result.exit_code` is never inspected,
matching ZAP's own noisy/non-standard exit codes (design D5/D2 precedent).
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.zap_adapter import (
    _MAX_INSTANCES_PER_ALERT,
    ZapAdapter,
    ZapFailedError,
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


def _adapter() -> ZapAdapter:
    """A `ZapAdapter` used only for `.parse()` in these tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return ZapAdapter(runner=FakeContainerRunner(), settings=_settings())


def _instance(
    *,
    uri: str = "https://target.example/login",
    method: str = "GET",
    param: str = "",
    evidence: str = "<form>",
) -> dict:
    return {"uri": uri, "method": method, "param": param, "evidence": evidence}


def _alert(
    *,
    pluginid: str = "10202",
    alert: str = "Absence of Anti-CSRF Tokens",
    riskcode: str = "2",
    confidence: str = "2",
    instances: list[dict] | None = None,
    cweid: str = "352",
    wascid: str = "9",
    solution: str = "Add anti-CSRF tokens.",
    alert_ref: str | None = None,
) -> dict:
    entry = {
        "pluginid": pluginid,
        "alert": alert,
        "riskcode": riskcode,
        "confidence": confidence,
        "instances": instances if instances is not None else [_instance()],
        "cweid": cweid,
        "wascid": wascid,
        "solution": solution,
    }
    if alert_ref is not None:
        entry["alert_ref"] = alert_ref
    return entry


def _report(*, site: list[dict] | None = None) -> str:
    if site is None:
        site = [{"alerts": [_alert()]}]
    return json.dumps({"site": site})


# ---------------------------------------------------------------------------
# 5.1 — golden fixture: whole-report -> Finding list
# ---------------------------------------------------------------------------


def test_parse_golden_fixture_produces_expected_finding() -> None:
    report = _report(
        site=[
            {
                "alerts": [
                    _alert(
                        pluginid="10202",
                        alert="Absence of Anti-CSRF Tokens",
                        riskcode="2",
                        instances=[
                            _instance(
                                uri="https://target.example/account?session=abc123",
                                method="GET",
                                param="",
                                evidence="<form>",
                            )
                        ],
                        alert_ref="10202-1",
                    )
                ]
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scan_task_id == _SCAN_TASK_ID
    assert finding.severity == FindingSeverity.MEDIUM
    assert finding.rule_id == "10202"
    assert finding.title == "Absence of Anti-CSRF Tokens"
    assert finding.file_path is None
    assert finding.line_number is None
    assert finding.snippet == "<form>"
    assert finding.raw_evidence is not None
    assert finding.raw_evidence["uri"] == "https://target.example/account?session=abc123"
    assert finding.raw_evidence["method"] == "GET"
    assert finding.raw_evidence["param"] == ""
    assert finding.raw_evidence["evidence"] == "<form>"
    assert finding.raw_evidence["cweid"] == "352"
    assert finding.raw_evidence["wascid"] == "9"
    assert finding.raw_evidence["confidence"] == "2"
    assert finding.raw_evidence["solution"] == "Add anti-CSRF tokens."
    assert finding.raw_evidence["alert_ref"] == "10202-1"
    assert finding.fingerprint != ""


def test_parse_missing_alert_ref_is_handled_gracefully() -> None:
    """`alert_ref` may be absent on some alerts — must not KeyError."""
    report = _report(site=[{"alerts": [_alert(alert_ref=None)]}])
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    assert findings[0].raw_evidence is not None
    assert findings[0].raw_evidence["alert_ref"] is None


# ---------------------------------------------------------------------------
# 5.1 — riskcode -> severity mapping, including unknown fallback
# ---------------------------------------------------------------------------


def test_parse_maps_every_riskcode_to_the_expected_severity() -> None:
    report = _report(
        site=[
            {
                "alerts": [
                    _alert(pluginid="1", riskcode="3", instances=[_instance()]),
                    _alert(pluginid="2", riskcode="2", instances=[_instance()]),
                    _alert(pluginid="3", riskcode="1", instances=[_instance()]),
                    _alert(pluginid="4", riskcode="0", instances=[_instance()]),
                ]
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["1"].severity == FindingSeverity.HIGH
    assert by_rule["2"].severity == FindingSeverity.MEDIUM
    assert by_rule["3"].severity == FindingSeverity.LOW
    assert by_rule["4"].severity == FindingSeverity.INFO


def test_parse_unknown_riskcode_falls_back_to_medium_and_does_not_fail_scan() -> None:
    report = _report(
        site=[{"alerts": [_alert(pluginid="99", riskcode="unknown-code", instances=[_instance()])]}]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    assert findings[0].severity == FindingSeverity.MEDIUM


# ---------------------------------------------------------------------------
# 5.1 — instance cap
# ---------------------------------------------------------------------------


def test_parse_caps_instances_per_alert_at_the_configured_maximum() -> None:
    many_instances = [_instance(uri=f"https://target.example/page{i}") for i in range(30)]
    report = _report(site=[{"alerts": [_alert(pluginid="10202", instances=many_instances)]}])
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert _MAX_INSTANCES_PER_ALERT == 25
    assert len(findings) == 25


# ---------------------------------------------------------------------------
# 5.1 — fingerprint excludes the query string
# ---------------------------------------------------------------------------


def test_fingerprint_excludes_the_query_string() -> None:
    report = _report(
        site=[
            {
                "alerts": [
                    _alert(
                        pluginid="10202",
                        instances=[
                            _instance(uri="https://target.example/account?session=abc123"),
                            _instance(uri="https://target.example/account?session=zzz999"),
                        ],
                    )
                ]
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert findings[0].fingerprint == findings[1].fingerprint


def test_fingerprint_differs_for_different_uri_paths() -> None:
    report = _report(
        site=[
            {
                "alerts": [
                    _alert(
                        pluginid="10202",
                        instances=[
                            _instance(uri="https://target.example/account"),
                            _instance(uri="https://target.example/profile"),
                        ],
                    )
                ]
            }
        ]
    )
    result = RunResult(exit_code=0, stdout=report, stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 2
    assert findings[0].fingerprint != findings[1].fingerprint


# ---------------------------------------------------------------------------
# 5.1 — timed_out / malformed / empty / site-less / zero-alerts
# ---------------------------------------------------------------------------


def test_parse_timed_out_raises_without_attempting_to_parse_stdout() -> None:
    """`timed_out=True` must raise for the timeout reason, not a JSON error —
    asserted by feeding garbage stdout alongside `timed_out=True`."""
    result = RunResult(
        exit_code=1, stdout="not even close to json {{{", stderr="deadline exceeded", timed_out=True
    )

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
        raise AssertionError("expected ZapFailedError")
    except ZapFailedError as exc:
        assert "timed out" in str(exc)


def test_parse_malformed_json_raises_zap_failed_error() -> None:
    result = RunResult(exit_code=0, stdout="{not valid json", stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
        raise AssertionError("expected ZapFailedError")
    except ZapFailedError:
        pass


def test_parse_empty_stdout_raises_zap_failed_error() -> None:
    result = RunResult(
        exit_code=0, stdout="", stderr="crashed before writing report", timed_out=False
    )

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
        raise AssertionError("expected ZapFailedError")
    except ZapFailedError:
        pass


def test_parse_json_missing_site_key_raises_zap_failed_error() -> None:
    """Syntactically valid JSON that is NOT a ZAP report shape at all (no
    `site` key whatsoever) is a genuine failure — distinct from a `site` key
    present with zero alerts, which is a valid empty scan (see below)."""
    result = RunResult(exit_code=0, stdout=json.dumps({}), stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
        raise AssertionError("expected ZapFailedError")
    except ZapFailedError:
        pass


def test_parse_empty_site_list_is_a_valid_zero_alert_success() -> None:
    result = RunResult(exit_code=0, stdout=_report(site=[]), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_site_with_no_alerts_is_a_valid_zero_alert_success() -> None:
    result = RunResult(
        exit_code=0, stdout=_report(site=[{"alerts": []}]), stderr="", timed_out=False
    )

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


# ---------------------------------------------------------------------------
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_zap_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_zap_adapter_supports_dast_but_not_sast_or_sca() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.DAST) is True
    assert adapter.supports(ScannerType.SAST) is False
    assert adapter.supports(ScannerType.SCA) is False
