"""Integration-level proof (Module 13c PR8) that the preflight actually
GATES `KubernetesSplitScanExecution` — closing PR7's SUGGESTION that this
was only proven at the unit level.

Deliberately exercises the REAL `validate_kubernetes_preflight` +
`KubernetesSplitScanExecution` + `FakeKubernetesJobRunner` collaborating
together through `create_kubernetes_scan_execution`, the sanctioned single
entry point — nothing here mocks the gate itself. A failing preflight must
leave `job_runner` completely untouched (no PVC/Job submitted); only a
passing preflight may ever construct a working executor.
"""

from __future__ import annotations

import uuid

import pytest

from orchestrator.domain.ports.kubernetes_preflight_port import StorageClassInfo
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.backend_selection import (
    KubernetesBackendNotSelectedError,
    KubernetesBackendUnavailableError,
    create_kubernetes_scan_execution,
    ensure_scan_execution_backend_available,
)
from orchestrator.infrastructure.kubernetes.kubernetes_preflight import KubernetesPreflightError
from tests.fakes.fake_cluster_capability import FakeClusterCapabilityPort
from tests.fakes.fake_kubernetes_job_runner import FakeKubernetesJobRunner

_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"


def _settings(*, backend: str = "kubernetes") -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://o:o@localhost/o",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="s",
        scan_execution_backend=backend,
        kubernetes_namespace=_NAMESPACE if backend == "kubernetes" else None,
        kubernetes_storage_class_name=_STORAGE_CLASS if backend == "kubernetes" else None,
    )


def _compatible_storage_class() -> StorageClassInfo:
    return StorageClassInfo(
        name=_STORAGE_CLASS,
        provisioner="kubernetes.io/aws-ebs",
        volume_binding_mode="WaitForFirstConsumer",
        allowed_access_modes=frozenset({"ReadWriteOnce"}),
    )


def test_ensure_scan_execution_backend_available_is_a_noop_for_docker() -> None:
    ensure_scan_execution_backend_available(_settings(backend="docker"))


def test_ensure_scan_execution_backend_available_fails_closed_for_kubernetes() -> None:
    """No concrete cluster adapter is wired in this build yet — selecting
    Kubernetes MUST fail deterministically rather than run half-provisioned
    or silently fall back to Docker."""
    with pytest.raises(KubernetesBackendUnavailableError):
        ensure_scan_execution_backend_available(_settings(backend="kubernetes"))


def test_create_kubernetes_scan_execution_refuses_when_docker_is_selected() -> None:
    capability_port = FakeClusterCapabilityPort()
    job_runner = FakeKubernetesJobRunner()

    with pytest.raises(KubernetesBackendNotSelectedError):
        create_kubernetes_scan_execution(
            _settings(backend="docker"),
            capability_port,
            job_runner,
            scanner_image="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:deadbeef",
            scanner_command=["detect"],
        )
    assert job_runner.pvc_calls == []
    assert job_runner.job_calls == []


def test_create_kubernetes_scan_execution_never_touches_runner_when_preflight_fails() -> None:
    capability_port = FakeClusterCapabilityPort()  # nothing seeded: fails closed
    job_runner = FakeKubernetesJobRunner()

    with pytest.raises(KubernetesPreflightError):
        create_kubernetes_scan_execution(
            _settings(),
            capability_port,
            job_runner,
            scanner_image="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:deadbeef",
            scanner_command=["detect"],
        )

    assert job_runner.pvc_calls == []
    assert job_runner.job_calls == []
    assert job_runner.delete_job_calls == []
    assert job_runner.delete_pvc_calls == []


def test_create_kubernetes_scan_execution_builds_a_working_executor_once_preflight_passes() -> None:
    capability_port = FakeClusterCapabilityPort()
    capability_port.seed_storage_class(_compatible_storage_class())
    capability_port.seed_enforced_namespace(_NAMESPACE)
    job_runner = FakeKubernetesJobRunner()

    execution = create_kubernetes_scan_execution(
        _settings(),
        capability_port,
        job_runner,
        scanner_image="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:deadbeef",
        scanner_command=["detect", "--no-git", "--source", "/workspace/checkout"],
    )
    result = execution.execute(
        clone_url="https://github.com/example/public-repo.git",
        ref="main",
        credential_ref=None,
        scan_task_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        scanner_type=ScannerType.SECRETS,
    )

    assert result.checkout_log == ""
    assert result.scanner_log == ""
    assert len(job_runner.job_calls) == 2
    # Success cleans up both Jobs + the PVC — no orphans (Deterministic PVC Lifecycle).
    assert len(job_runner.delete_job_calls) == 2
    assert len(job_runner.delete_pvc_calls) == 1
