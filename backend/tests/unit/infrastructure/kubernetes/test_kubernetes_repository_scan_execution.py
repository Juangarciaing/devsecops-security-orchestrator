"""`KubernetesRepositoryScanExecution` — the `ScanExecutionPort` bridge
(k8s-backend-enable PR5, tasks 5.13-5.14). Proven ONLY against
`FakeKubernetesJobRunner` — no live cluster; live proof lives in
`tests/integration/test_kubernetes_repository_scan_execution_live.py`.
"""

from __future__ import annotations

import uuid

import pytest

from orchestrator.domain.ports.kubernetes_job_runner_port import (
    JobOutcome,
    JobSpec,
    KubernetesJobRunnerPort,
    PvcSpec,
)
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_repository_scan_execution import (
    KubernetesRepositoryScanExecution,
    _extract_gitleaks_json_report,
)
from orchestrator.infrastructure.kubernetes.kubernetes_scan_execution import (
    KubernetesPrivateRepositoryError,
)
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError
from tests.fakes.fake_kubernetes_job_runner import FakeKubernetesJobRunner

_NAMESPACE = "security-scans"
_SCAN_TASK_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "database_url": "postgresql://o:o@localhost/o",
        "redis_url": "redis://localhost:6379/0",
        "secret_key": "s",
        "jwt_secret_key": "j",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _bridge(runner: KubernetesJobRunnerPort) -> KubernetesRepositoryScanExecution:
    return KubernetesRepositoryScanExecution(
        runner,
        namespace=_NAMESPACE,
        checkout_image="alpine/git:2.54.0@sha256:deadbeef",
        settings=_settings(),
        timeout_seconds=90,
    )


class _ExplodingJobRunner(KubernetesJobRunnerPort):
    """Every method raises — proves a caller reached zero of them."""

    def _boom(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("KubernetesJobRunnerPort must not be called")

    def get_pvc(self, namespace: str, name: str) -> bool:
        self._boom()
        return False

    def create_pvc(self, spec: PvcSpec) -> None:
        self._boom()

    def get_job(self, namespace: str, name: str) -> bool:
        self._boom()
        return False

    def create_job(self, spec: JobSpec) -> None:
        self._boom()

    def wait_for_job(self, namespace: str, name: str, timeout_seconds: int) -> JobOutcome:
        self._boom()
        raise AssertionError

    def get_job_logs(self, namespace: str, name: str, max_bytes: int) -> str:
        self._boom()
        return ""

    def delete_job(self, namespace: str, name: str) -> None:
        self._boom()

    def delete_pvc(self, namespace: str, name: str) -> None:
        self._boom()

    def list_job_names(self, namespace: str) -> list[str]:
        self._boom()
        return []

    def list_pvc_names(self, namespace: str) -> list[str]:
        self._boom()
        return []


def test_private_repository_raises_before_any_port_call() -> None:
    runner = _ExplodingJobRunner()
    credential = Secret(value="vault:secret/example-repo")

    with pytest.raises(KubernetesPrivateRepositoryError) as exc_info:
        _bridge(runner).execute(
            "https://github.com/example/private-repo.git",
            "main",
            _SCAN_TASK_ID,
            ScannerType.SECRETS,
            credential=credential,
        )

    assert "vault:secret/example-repo" not in str(exc_info.value)


#: A REAL combined stdout+stderr Pod log, byte-for-byte as observed live
#: against `kind-devsecops-orchestrator` (task 5.18) — Gitleaks' own
#: ANSI-colored `INF`/`WRN` status lines land AHEAD of the
#: `--report-path=/dev/stdout` JSON report in Kubernetes' single merged log
#: stream (genuine platform difference from Docker, discovered live; see
#: `_extract_gitleaks_json_report`'s docstring). Fixtures below use this
#: shape, not pure JSON, so this suite would have caught that bug too.
_REAL_DIRTY_SCANNER_LOG = (
    "\x1b[90m3:25PM\x1b[0m \x1b[32mINF\x1b[0m \x1b[1mscanned ~3373 bytes in 6.04ms\x1b[0m\n"
    "\x1b[90m3:25PM\x1b[0m \x1b[33mWRN\x1b[0m \x1b[1mleaks found: 1\x1b[0m\n"
    '[\n {\n  "RuleID": "aws-key",\n  "Description": "AWS Key",\n  "File": "a.py",\n'
    '  "StartLine": 3,\n  "Secret": "s3cr3t"\n }\n]\n'
)
_REAL_CLEAN_SCANNER_LOG = (
    "\x1b[90m3:27PM\x1b[0m \x1b[32mINF\x1b[0m \x1b[1mscanned ~13 bytes (13 bytes) in 654µs\x1b[0m\n"
    "\x1b[90m3:27PM\x1b[0m \x1b[32mINF\x1b[0m \x1b[1mno leaks found\x1b[0m\n[]\n"
)


def test_extract_gitleaks_json_report_recovers_the_array_from_a_real_combined_log() -> None:
    assert _extract_gitleaks_json_report(_REAL_DIRTY_SCANNER_LOG).startswith("[\n {")
    assert _extract_gitleaks_json_report(_REAL_CLEAN_SCANNER_LOG).strip() == "[]"


def test_successful_public_repo_scan_parses_findings_via_the_unmodified_gitleaks_adapter() -> None:
    runner = FakeKubernetesJobRunner()
    runner.script_logs(
        _NAMESPACE,
        "scan-11111111222233334444-scanner",
        _REAL_DIRTY_SCANNER_LOG,
    )
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-revparse", "deadbeef00\n")
    runner.script_wait_outcomes(
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # checkout
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # rev-parse
        JobOutcome(succeeded=False, failed=True, timed_out=False),  # scanner: exit 2
    )
    runner.script_exit_code(None)
    runner.script_exit_code(None)
    runner.script_exit_code(2)

    result = _bridge(runner).execute(
        "https://github.com/example/public-repo.git",
        "main",
        _SCAN_TASK_ID,
        ScannerType.SECRETS,
    )

    assert result.head_sha == "deadbeef00"
    assert len(result.findings) == 1
    assert result.findings[0].rule_id == "aws-key"


def test_clean_scan_exit_zero_returns_zero_findings() -> None:
    runner = FakeKubernetesJobRunner()
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-revparse", "deadbeef00\n")
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-scanner", _REAL_CLEAN_SCANNER_LOG)
    # Everything succeeds (Job exit 0) — default outcomes/exit codes apply.

    result = _bridge(runner).execute(
        "https://github.com/example/public-repo.git",
        "main",
        _SCAN_TASK_ID,
        ScannerType.SECRETS,
    )

    assert result.findings == []
    assert result.head_sha == "deadbeef00"


def test_genuine_gitleaks_failure_still_raises_through_the_unmodified_adapter() -> None:
    """Exit 1 (a real Gitleaks error, never "leaks found") must still raise
    `GitleaksFailedError` — the bridge does not swallow genuine failures,
    only reclassifies the `--exit-code=2` "leaks found" case."""
    runner = FakeKubernetesJobRunner()
    runner.script_wait_outcomes(
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # checkout
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # rev-parse
        JobOutcome(succeeded=False, failed=True, timed_out=False),  # scanner: exit 1
    )
    runner.script_exit_code(None)
    runner.script_exit_code(None)
    runner.script_exit_code(1)

    with pytest.raises(GitleaksFailedError):
        _bridge(runner).execute(
            "https://github.com/example/public-repo.git",
            "main",
            _SCAN_TASK_ID,
            ScannerType.SECRETS,
        )


def test_unsupported_scanner_type_raises_before_any_port_call() -> None:
    runner = _ExplodingJobRunner()

    with pytest.raises(ValueError, match="sast"):
        _bridge(runner).execute(
            "https://github.com/example/public-repo.git",
            "main",
            _SCAN_TASK_ID,
            ScannerType.SAST,
        )
