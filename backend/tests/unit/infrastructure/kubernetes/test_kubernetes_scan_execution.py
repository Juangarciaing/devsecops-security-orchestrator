"""RED→GREEN tests for `KubernetesSplitScanExecution` (Module 13c PR6).

Proven ONLY against `FakeKubernetesJobRunner` — no live cluster, no
`process_scan_task` wiring (PR8), no Kustomize/RBAC rendering (PR7). Docker
stays the sole active backend; this suite exists to prove the disabled
Kubernetes lifecycle is correct in isolation before it is ever wired in.
"""

from __future__ import annotations

import uuid

import pytest

from orchestrator.domain.ports.kubernetes_job_runner_port import JobOutcome
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.kubernetes.kubernetes_scan_execution import (
    KubernetesPrivateRepositoryError,
    KubernetesSplitScanExecution,
    KubernetesTransientError,
    KubernetesWorkloadFailedError,
)
from tests.fakes.fake_kubernetes_job_runner import FakeKubernetesJobRunner

_NAMESPACE = "security-scans"
_SCAN_TASK_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _execution(
    runner: FakeKubernetesJobRunner, *, scanner_exit_codes_are_data: bool = False
) -> KubernetesSplitScanExecution:
    return KubernetesSplitScanExecution(
        runner,
        namespace=_NAMESPACE,
        checkout_image="alpine/git:2.54.0@sha256:deadbeef",
        scanner_image="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:deadbeef",
        scanner_command=["detect", "--no-git", "--source", "/workspace/checkout"],
        timeout_seconds=90,
        scanner_exit_codes_are_data=scanner_exit_codes_are_data,
    )


def test_public_repo_creates_pvc_then_split_jobs_with_hardened_mounts() -> None:
    runner = FakeKubernetesJobRunner()
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-checkout", "cloned ok")
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-scanner", "no leaks found")

    result = _execution(runner).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SECRETS,
    )

    assert result.checkout_log == "cloned ok"
    assert result.scanner_log == "no leaks found"
    assert len(runner.pvc_calls) == 1
    assert runner.pvc_calls[0].access_mode == "ReadWriteOnce"
    assert runner.pvc_calls[0].volume_binding_mode == "WaitForFirstConsumer"

    assert len(runner.job_calls) == 2
    checkout_spec, scanner_spec = runner.job_calls
    assert checkout_spec.pvc_read_only is False
    assert checkout_spec.allow_network_egress is True
    assert scanner_spec.pvc_read_only is True
    assert scanner_spec.allow_network_egress is False
    assert scanner_spec.env == {}
    assert checkout_spec.pvc_name == scanner_spec.pvc_name == runner.pvc_calls[0].name

    # Success cleans up both Jobs and the PVC — no orphans left behind.
    assert len(runner.delete_job_calls) == 2
    assert runner.delete_pvc_calls == [(_NAMESPACE, runner.pvc_calls[0].name)]


def test_job_names_are_bounded_and_namespaced_to_the_task() -> None:
    runner = FakeKubernetesJobRunner()
    _execution(runner).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SAST,
    )

    for spec in runner.job_calls:
        assert len(spec.name) <= 63
        assert str(_SCAN_TASK_ID.hex[:20]) in spec.name
    assert len(runner.pvc_calls[0].name) <= 63


def test_job_spec_has_conservative_hardening_defaults() -> None:
    runner = FakeKubernetesJobRunner()
    _execution(runner).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SEMGREP,
    )

    for spec in runner.job_calls:
        assert spec.backoff_limit == 0
        assert spec.active_deadline_seconds == 90 + 30
        assert spec.ttl_seconds_after_finished > 0
        assert spec.memory_mb > 0
        assert spec.cpu_millis > 0
        assert spec.pids_limit > 0


def test_private_repository_fails_before_any_workload_is_created() -> None:
    runner = FakeKubernetesJobRunner()

    with pytest.raises(KubernetesPrivateRepositoryError) as exc_info:
        _execution(runner).execute(
            clone_url="https://github.com/example/private-repo.git",
            ref="main",
            credential_ref="vault:secret/example-repo",
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SECRETS,
        )

    assert "vault:secret/example-repo" not in str(exc_info.value)
    assert runner.pvc_calls == []
    assert runner.job_calls == []


@pytest.mark.parametrize("failing_job_index", [0, 1])
def test_workload_failure_is_terminal_and_still_cleans_up(failing_job_index: int) -> None:
    runner = FakeKubernetesJobRunner()
    outcomes = [
        JobOutcome(succeeded=True, failed=False, timed_out=False),
        JobOutcome(succeeded=True, failed=False, timed_out=False),
    ]
    outcomes[failing_job_index] = JobOutcome(succeeded=False, failed=True, timed_out=False)
    runner.script_wait_outcomes(*outcomes)

    with pytest.raises(KubernetesWorkloadFailedError):
        _execution(runner).execute(
            clone_url="https://github.com/example/public-repo.git",
            ref="main",
            credential_ref=None,
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SCA,
        )

    assert len(runner.delete_job_calls) == 2
    assert len(runner.delete_pvc_calls) == 1


@pytest.mark.parametrize("failure_mode", ["submission", "polling"])
def test_infrastructure_failure_is_transient_and_still_cleans_up(failure_mode: str) -> None:
    runner = FakeKubernetesJobRunner()
    if failure_mode == "submission":
        runner.script_create_job_error(RuntimeError("apiserver unavailable"))
    else:
        runner.script_wait_error(RuntimeError("watch connection reset"))

    with pytest.raises(KubernetesTransientError):
        _execution(runner).execute(
            clone_url="https://github.com/example/public-repo.git",
            ref="main",
            credential_ref=None,
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SECRETS,
        )

    assert len(runner.delete_job_calls) == 2
    assert len(runner.delete_pvc_calls) == 1


def test_timed_out_job_is_terminal_not_transient() -> None:
    runner = FakeKubernetesJobRunner()
    runner.script_wait_outcomes(JobOutcome(succeeded=False, failed=False, timed_out=True))

    with pytest.raises(KubernetesWorkloadFailedError):
        _execution(runner).execute(
            clone_url="https://github.com/example/public-repo.git",
            ref="main",
            credential_ref=None,
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SECRETS,
        )


def test_duplicate_delivery_discovers_existing_resources_without_recreating() -> None:
    """A worker crash after checkout-Job creation, then Celery redelivery, must not duplicate."""
    runner = FakeKubernetesJobRunner()
    pvc_name = "scan-11111111222233334444-pvc"
    checkout_name = "scan-11111111222233334444-checkout"
    runner.seed_existing_pvc(_NAMESPACE, pvc_name)
    runner.seed_existing_job(_NAMESPACE, checkout_name)

    _execution(runner).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SECRETS,
    )

    # The already-existing PVC and checkout Job were discovered, not recreated —
    # only the scanner Job (never seeded) went through `create_job`.
    assert runner.pvc_calls == []
    assert len(runner.job_calls) == 1
    assert runner.job_calls[0].name == "scan-11111111222233334444-scanner"


# ---------------------------------------------------------------------------
# k8s-backend-enable PR5 (tasks 5.5-5.10) — `scanner_exit_codes_are_data` +
# the rev-parse Job/`head_sha`. Both new behaviors are gated behind the SAME
# keyword-only flag (default `False`): the 8 tests above construct
# `KubernetesSplitScanExecution` via `_execution()`'s default
# (`scanner_exit_codes_are_data=False`) and are therefore completely
# unaffected by anything below — no rev-parse Job runs, `job_calls`/
# `delete_job_calls` counts stay at exactly 2, byte-for-byte identical to
# before this PR (the hard regression guard, tasks 5.1/5.16).
# ---------------------------------------------------------------------------


def test_default_flag_runs_no_revparse_job_and_leaves_head_sha_empty() -> None:
    """Explicit companion to the 8 tests above: confirms the additive
    `KubernetesScanResult` fields default to "no rev-parse Job ran"."""
    runner = FakeKubernetesJobRunner()

    result = _execution(runner).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SECRETS,
    )

    assert result.head_sha == ""
    assert len(runner.job_calls) == 2
    assert len(runner.delete_job_calls) == 2


def test_scanner_exit_codes_are_data_true_returns_non_zero_scanner_outcome_as_data() -> None:
    """Gitleaks' `--exit-code=2` (leaks found) must reach the caller as
    `KubernetesScanResult.scanner_exit_code` data, never as
    `KubernetesWorkloadFailedError` — the concrete fix for design bug #2
    (scanner exit codes structurally lost)."""
    runner = FakeKubernetesJobRunner()
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-scanner", '[{"RuleID": "aws-key"}]')
    runner.script_wait_outcomes(
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # checkout
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # rev-parse
        JobOutcome(succeeded=False, failed=True, timed_out=False),  # scanner
    )
    # `script_exit_code` is consumed in call order, same as `script_wait_outcomes`
    # — the first two (checkout/rev-parse) are irrelevant/unobserved, the 3rd
    # (scanner) is Gitleaks' real `--exit-code=2`.
    runner.script_exit_code(None)
    runner.script_exit_code(None)
    runner.script_exit_code(2)

    result = _execution(runner, scanner_exit_codes_are_data=True).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SECRETS,
    )

    assert result.scanner_exit_code == 2
    assert '"RuleID"' in result.scanner_log
    assert len(runner.job_calls) == 3
    assert len(runner.delete_job_calls) == 3


def test_scanner_exit_codes_are_data_true_checkout_failure_still_raises() -> None:
    """The checkout Job stays strict regardless of `scanner_exit_codes_are_data`
    — only the scanner Job's non-zero exit is ever data."""
    runner = FakeKubernetesJobRunner()
    runner.script_wait_outcomes(JobOutcome(succeeded=False, failed=True, timed_out=False))

    with pytest.raises(KubernetesWorkloadFailedError):
        _execution(runner, scanner_exit_codes_are_data=True).execute(
            clone_url="https://github.com/example/public-repo.git",
            ref="main",
            credential_ref=None,
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SECRETS,
        )

    # Cleanup still runs for all 3 possible Job names (idempotent no-op for
    # the rev-parse/scanner Jobs that never got created).
    assert len(runner.delete_job_calls) == 3
    assert len(runner.delete_pvc_calls) == 1


def test_scanner_exit_codes_are_data_true_scanner_timeout_still_raises() -> None:
    """A scanner Job that times out (never reaches a real exit code) must
    stay terminal even under `scanner_exit_codes_are_data=True` — a timeout
    is not "exit-code data"."""
    runner = FakeKubernetesJobRunner()
    runner.script_wait_outcomes(
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # checkout
        JobOutcome(succeeded=True, failed=False, timed_out=False),  # rev-parse
        JobOutcome(succeeded=False, failed=True, timed_out=True),  # scanner
    )

    with pytest.raises(KubernetesWorkloadFailedError):
        _execution(runner, scanner_exit_codes_are_data=True).execute(
            clone_url="https://github.com/example/public-repo.git",
            ref="main",
            credential_ref=None,
            scan_task_id=_SCAN_TASK_ID,
            scanner_type=ScannerType.SECRETS,
        )


def test_revparse_job_runs_between_checkout_and_scanner_and_populates_head_sha() -> None:
    runner = FakeKubernetesJobRunner()
    runner.script_logs(_NAMESPACE, "scan-11111111222233334444-revparse", "abc123def456\n")

    result = _execution(runner, scanner_exit_codes_are_data=True).execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=_SCAN_TASK_ID,
        scanner_type=ScannerType.SECRETS,
    )

    assert result.head_sha == "abc123def456"
    assert len(runner.job_calls) == 3
    checkout_spec, revparse_spec, scanner_spec = runner.job_calls
    assert checkout_spec.labels["component"] == "checkout"
    assert revparse_spec.labels["component"] == "scanner"
    assert revparse_spec.pvc_read_only is True
    assert revparse_spec.allow_network_egress is False
    assert revparse_spec.command == ["-C", "/workspace/checkout", "rev-parse", "HEAD"]
    assert revparse_spec.name == "scan-11111111222233334444-revparse"
    assert scanner_spec.labels["component"] == "scanner"
