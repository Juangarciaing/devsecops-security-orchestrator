"""`GitleaksAdapter` — JSON-to-`Finding` parser (Module 6 PR2, tasks 2.1-2.3;
retrofitted to `ScannerAdapterPort` in Module 7 PR1, tasks 2.1-2.2 —
`parse()` moved from a module-level function to a method).

`.parse()` is a pure method: exit 0 -> no findings, exit 2 + JSON report ->
parsed `Finding`s, anything else (or `timed_out=True`) -> `GitleaksFailedError`
(D4/D5 — never conflate "leaks found" with a genuine tool failure).
Container-invocation shape is covered by
`tests/integration/test_gitleaks_adapter_live.py` (real Docker); the compat
`scan(volume_name)` shape tests were removed in Module 13c PR5c-1. Clean-run,
malformed-input, and finding-redaction parser cases are now owned solely by
`test_gitleaks_parser_contract.py` (Module 13c PR5c-2) — this file keeps
only cases with no parser-contract analog.
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksAdapter
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


def _adapter() -> GitleaksAdapter:
    """A `GitleaksAdapter` used only for `.parse()` in these tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return GitleaksAdapter(runner=FakeContainerRunner(), settings=_settings())


# ---------------------------------------------------------------------------
# 2.2 — parse(RunResult)
# ---------------------------------------------------------------------------


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

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 3
    assert {f.rule_id for f in findings} == {"generic-api-key", "slack-token"}
    # Distinct secrets/files/lines -> distinct fingerprints (dedup key).
    assert len({f.fingerprint for f in findings}) == 3


def test_parse_uses_rule_id_as_title_fallback_when_description_missing() -> None:
    report = [{"RuleID": "generic-secret", "File": "x.py", "StartLine": 1, "Secret": "s"}]
    result = RunResult(exit_code=2, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert findings[0].title == "generic-secret"


# ---------------------------------------------------------------------------
# Module 7 PR1 — `ScannerAdapterPort` retrofit
# ---------------------------------------------------------------------------


def test_gitleaks_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_gitleaks_adapter_supports_secrets_but_not_sast() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SECRETS) is True
    assert adapter.supports(ScannerType.SAST) is False


def test_module_level_parse_function_no_longer_exists() -> None:
    """Module 7 tasks 2.2/6.1: the old module-level `parse()` shim is
    DELETED once `GitleaksAdapter.parse()` exists — no dead duplicate entry
    point left behind."""
    import orchestrator.infrastructure.scanners.gitleaks_adapter as gitleaks_adapter_module

    assert not hasattr(gitleaks_adapter_module, "parse")
