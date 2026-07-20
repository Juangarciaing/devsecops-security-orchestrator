"""`PipAuditAdapter` — pre-flight probe + argv builder + JSON-to-`Finding`
parser (Module 11 PR1, tasks 1.4-1.6).

`PipAuditAdapter.scan()` proves the exact two-call `ContainerRunnerPort.run()`
shape (network-off probe, then network-on audit) via `FakeContainerRunner` —
no real Docker socket needed here; the live proof lives in
`tests/integration/test_pip_audit_adapter_live.py` (PR2). `.parse()` is a
pure method: `timed_out=True` -> `PipAuditFailedError`; valid JSON with a
`dependencies` key -> parsed `Finding`s (possibly zero); anything else ->
`PipAuditFailedError` (D4 — pip-audit's exit code is ambiguous between
"vulns found" and "genuine error", so success/failure is parse-driven, not
exit-code-driven).
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import FindingSeverity, ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.pip_audit_adapter import (
    _PIP_AUDIT_ARGV,
    PipAuditAdapter,
    PipAuditFailedError,
)
from tests.fakes.fake_container_runner import FakeContainerRunner

_SCAN_TASK_ID = uuid.uuid4()
_PROBE_PRESENT_RESULT = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)
_PROBE_ABSENT_RESULT = RunResult(exit_code=1, stdout="", stderr="", timed_out=False)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def _adapter(runner: FakeContainerRunner | None = None) -> PipAuditAdapter:
    """A `PipAuditAdapter` used only for `.parse()` in most tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return PipAuditAdapter(runner=runner or FakeContainerRunner(), settings=_settings())


# ---------------------------------------------------------------------------
# 1.4 — probe short-circuit / `.scan()` call shape
# ---------------------------------------------------------------------------


def test_scan_probes_manifest_presence_first_network_off() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _PROBE_PRESENT_RESULT, RunResult(exit_code=0, stdout="{}", stderr="", timed_out=False)
    )
    settings = _settings()
    adapter = PipAuditAdapter(runner=fake_runner, settings=settings)

    adapter.scan("scan-abc123")

    assert len(fake_runner.calls) == 2
    probe_call = fake_runner.calls[0]
    assert probe_call.image == settings.scan_pip_audit_image
    assert probe_call.volume_name == "scan-abc123"
    assert probe_call.mount_path == "/checkout"
    assert probe_call.read_only_mount is True
    assert probe_call.network_disabled is True
    assert probe_call.timeout_seconds == settings.scan_timeout_seconds
    assert probe_call.command[0] == "python"
    assert "requirements.txt" in probe_call.command[-1]


def test_scan_runs_pip_audit_network_on_when_manifest_present() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        _PROBE_PRESENT_RESULT, RunResult(exit_code=0, stdout="{}", stderr="", timed_out=False)
    )
    settings = _settings()
    adapter = PipAuditAdapter(runner=fake_runner, settings=settings)

    adapter.scan("scan-abc123")

    assert len(fake_runner.calls) == 2
    audit_call = fake_runner.calls[1]
    assert audit_call.command == list(_PIP_AUDIT_ARGV)
    assert audit_call.image == settings.scan_pip_audit_image
    assert audit_call.volume_name == "scan-abc123"
    assert audit_call.mount_path == "/checkout"
    assert audit_call.read_only_mount is True
    assert audit_call.network_disabled is False
    assert audit_call.timeout_seconds == settings.scan_timeout_seconds
    assert audit_call.limits.memory_mb == settings.scan_memory_limit_mb
    assert audit_call.limits.pids_limit == settings.scan_pids_limit


def test_scan_short_circuits_to_synthetic_empty_result_when_manifest_absent() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(_PROBE_ABSENT_RESULT)
    adapter = PipAuditAdapter(runner=fake_runner, settings=_settings())

    result = adapter.scan("scan-no-manifest")

    # Only the probe launched — no network-enabled container for a
    # guaranteed no-op (D3).
    assert len(fake_runner.calls) == 1
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"dependencies": []}
    assert result.timed_out is False


def test_synthetic_empty_result_parses_to_zero_findings() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(_PROBE_ABSENT_RESULT)
    adapter = PipAuditAdapter(runner=fake_runner, settings=_settings())

    result = adapter.scan("scan-no-manifest")
    findings = adapter.parse(result, _SCAN_TASK_ID)

    assert findings == []


# ---------------------------------------------------------------------------
# 1.4 — parse(RunResult)
# ---------------------------------------------------------------------------


def test_parse_empty_dependencies_returns_no_findings() -> None:
    result = RunResult(exit_code=0, stdout='{"dependencies": []}', stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_one_dependency_with_one_vuln_returns_one_finding_with_all_fields_mapped() -> None:
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
                        "aliases": ["CVE-2018-18074"],
                    }
                ],
            }
        ]
    }
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scan_task_id == _SCAN_TASK_ID
    assert finding.rule_id == "PYSEC-2018-28"
    assert "requests" in finding.title
    assert "PYSEC-2018-28" in finding.title
    assert finding.severity == FindingSeverity.MEDIUM
    assert finding.file_path == "requirements.txt"
    assert finding.raw_evidence is not None
    expected_description = report["dependencies"][0]["vulns"][0]["description"]
    assert finding.raw_evidence["description"] == expected_description
    assert finding.raw_evidence["fix_versions"] == ["2.20.0"]
    assert finding.snippet
    assert finding.fingerprint


def test_parse_exit_code_1_with_valid_json_is_success_not_error() -> None:
    """pip-audit's exit code is ambiguous (1 == vulns found OR genuine
    error) — D4: success/failure is parse-driven, exit code is ignored."""
    report = {"dependencies": [{"name": "safe-pkg", "version": "1.0.0", "vulns": []}]}
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings == []


def test_parse_multiple_dependencies_and_vulns_triangulation() -> None:
    report = {
        "dependencies": [
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "vulns": [
                    {"id": "GHSA-aaaa", "description": "desc a", "fix_versions": ["1.0.1"]},
                    {"id": "GHSA-bbbb", "description": "desc b", "fix_versions": []},
                ],
            },
            {
                "name": "pkg-b",
                "version": "2.0.0",
                "vulns": [{"id": "GHSA-cccc", "description": "desc c", "fix_versions": ["2.0.1"]}],
            },
        ]
    }
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 3
    assert {f.rule_id for f in findings} == {"GHSA-aaaa", "GHSA-bbbb", "GHSA-cccc"}
    assert len({f.fingerprint for f in findings}) == 3


def test_parse_timed_out_raises_pip_audit_failed_error_even_with_exit_code_0() -> None:
    result = RunResult(exit_code=0, stdout="", stderr="", timed_out=True)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except PipAuditFailedError:
        pass
    else:
        raise AssertionError("expected PipAuditFailedError")


def test_parse_empty_stdout_raises_pip_audit_failed_error() -> None:
    result = RunResult(exit_code=1, stdout="", stderr="pip-audit crashed", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except PipAuditFailedError as exc:
        assert "pip-audit crashed" in str(exc)
    else:
        raise AssertionError("expected PipAuditFailedError")


def test_parse_malformed_json_raises_pip_audit_failed_error() -> None:
    result = RunResult(exit_code=1, stdout="{not valid json", stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except PipAuditFailedError:
        pass
    else:
        raise AssertionError("expected PipAuditFailedError")


def test_parse_json_without_dependencies_key_raises_pip_audit_failed_error() -> None:
    result = RunResult(exit_code=1, stdout='{"unexpected": true}', stderr="", timed_out=False)

    try:
        _adapter().parse(result, _SCAN_TASK_ID)
    except PipAuditFailedError:
        pass
    else:
        raise AssertionError("expected PipAuditFailedError")


# ---------------------------------------------------------------------------
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_pip_audit_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_pip_audit_adapter_supports_sca_but_not_secrets() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SCA) is True
    assert adapter.supports(ScannerType.SECRETS) is False
