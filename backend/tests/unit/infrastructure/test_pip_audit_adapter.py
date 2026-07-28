"""`PipAuditAdapter` — JSON-to-`Finding` parser (Module 11 PR1, tasks 1.4-1.6).

`.parse()` is a pure method: `timed_out=True` -> `PipAuditFailedError`; valid
JSON with a `dependencies` key -> parsed `Finding`s (possibly zero); anything
else -> `PipAuditFailedError` (D4 — pip-audit's exit code is ambiguous
between "vulns found" and "genuine error", so success/failure is
parse-driven, not exit-code-driven). Probe/argv/network-toggle shape is
covered by `tests/unit/infrastructure/test_pip_audit_docker_execution.py`
(the descriptor's production path) and
`tests/integration/test_pip_audit_adapter_live.py` (real Docker); the
compat `scan(volume_name)` shape tests were removed in Module 13c PR5c-1.
Clean-run, malformed-input, and finding-redaction parser cases are now owned
solely by `test_pip_audit_parser_contract.py` (Module 13c PR5c-2) — this
file keeps only cases with no parser-contract analog.
"""

from __future__ import annotations

import json
import uuid

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.scanners.pip_audit_adapter import PipAuditAdapter
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


def _adapter() -> PipAuditAdapter:
    """A `PipAuditAdapter` used only for `.parse()` in these tests — no
    container calls, so a fresh unscripted `FakeContainerRunner` is fine."""
    return PipAuditAdapter(runner=FakeContainerRunner(), settings=_settings())


# ---------------------------------------------------------------------------
# 1.4 — parse(RunResult)
# ---------------------------------------------------------------------------


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


def test_parse_deduplicates_a_vuln_id_repeated_within_the_same_dependency() -> None:
    """Real-Docker discovery (PR2 mandatory live proof): pip-audit's REAL
    output for `requests==2.19.0` lists `PYSEC-2023-74` TWICE in the SAME
    dependency's `vulns` array (confirmed against the real pinned image, not
    assumed) — same `id`/`name`/`version`, so the naive per-vuln mapping
    produced two `Finding`s with an IDENTICAL `fingerprint`. Because
    `bulk_upsert_findings` batches every `Finding` from one scan into a
    SINGLE multi-row `INSERT ... ON CONFLICT (repository_id, fingerprint) DO
    UPDATE`, a same-batch duplicate fingerprint crashes Postgres with
    `CardinalityViolationError: ON CONFLICT DO UPDATE command cannot affect
    row a second time` — reproduced live, not hypothetical. `parse()` must
    dedupe by fingerprint within one report, keeping the first occurrence."""
    report = {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.19.0",
                "vulns": [
                    {
                        "id": "PYSEC-2023-74",
                        "description": "first occurrence",
                        "fix_versions": ["2.31.0"],
                    },
                    {
                        "id": "PYSEC-2023-74",
                        "description": "second occurrence (real pip-audit duplicate)",
                        "fix_versions": ["2.31.0"],
                    },
                ],
            }
        ]
    }
    result = RunResult(exit_code=1, stdout=json.dumps(report), stderr="", timed_out=False)

    findings = _adapter().parse(result, _SCAN_TASK_ID)

    assert len(findings) == 1
    assert findings[0].rule_id == "PYSEC-2023-74"
    assert findings[0].snippet is not None and "first occurrence" in findings[0].snippet


# ---------------------------------------------------------------------------
# `ScannerAdapterPort` contract
# ---------------------------------------------------------------------------


def test_pip_audit_adapter_implements_scanner_adapter_port() -> None:
    assert isinstance(_adapter(), ScannerAdapterPort)


def test_pip_audit_adapter_supports_sca_but_not_secrets() -> None:
    adapter = _adapter()

    assert adapter.supports(ScannerType.SCA) is True
    assert adapter.supports(ScannerType.SECRETS) is False
