"""Unit-level proof (k8s-backend-enable PR6, design D-Routing) that
`ensure_scan_execution_backend_available`/`create_kubernetes_scan_execution`
run the REAL preflight against a freshly built `ClusterCapabilityPort`/
`KubernetesJobRunnerPort` rather than the unconditional raise this module
carried through PR1-PR5.

Live cluster construction (`_build_cluster_capability`/`_build_job_runner`)
and `load_kubernetes_config` are monkeypatched to injected fakes here — this
file proves the WIRING/fail-closed contract without needing a real cluster;
the actual live proof is `tests/integration/test_process_scan_task_kubernetes_live.py`
(tasks 6.9-6.11).
"""

from __future__ import annotations

import uuid

import pytest

from orchestrator.domain.ports.kubernetes_preflight_port import StorageClassInfo
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes import backend_selection
from orchestrator.infrastructure.kubernetes.backend_selection import (
    KubernetesBackendNotSelectedError,
    KubernetesBackendUnavailableError,
    create_kubernetes_scan_execution,
    ensure_scan_execution_backend_available,
)
from orchestrator.infrastructure.kubernetes.kubernetes_preflight import KubernetesPreflightError
from orchestrator.infrastructure.kubernetes.kubernetes_repository_scan_execution import (
    KubernetesRepositoryScanExecution,
)
from orchestrator.infrastructure.kubernetes.kubernetes_scanner_descriptor import (
    UnsupportedScannerTypeError,
)
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


def _ready_capability() -> FakeClusterCapabilityPort:
    capability_port = FakeClusterCapabilityPort()
    capability_port.seed_ready_namespace(_NAMESPACE)
    capability_port.seed_storage_class(_compatible_storage_class())
    capability_port.seed_enforced_namespace(_NAMESPACE)
    return capability_port


# ---------------------------------------------------------------------------
# ensure_scan_execution_backend_available
# ---------------------------------------------------------------------------


def test_ensure_scan_execution_backend_available_is_a_noop_for_docker() -> None:
    ensure_scan_execution_backend_available(_settings(backend="docker"))


def test_ensure_scan_execution_backend_available_wraps_a_config_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine client-configuration failure (no reachable kubeconfig
    context, no in-cluster token) is wrapped as `KubernetesBackendUnavailableError`
    — the ONLY thing that error means post-PR6."""

    def _explode(_settings: Settings) -> None:
        raise RuntimeError("no configuration could be loaded")

    monkeypatch.setattr(backend_selection, "load_kubernetes_config", _explode)

    with pytest.raises(KubernetesBackendUnavailableError):
        ensure_scan_execution_backend_available(_settings())


def test_ensure_scan_execution_backend_available_fails_closed_on_a_real_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config loads fine, but the cluster cannot prove isolation — this MUST
    raise `KubernetesPreflightError` directly, UNTOUCHED (not wrapped as
    `KubernetesBackendUnavailableError` — the two are now distinct failures)."""
    monkeypatch.setattr(backend_selection, "load_kubernetes_config", lambda _settings: None)
    monkeypatch.setattr(
        backend_selection,
        "_build_cluster_capability",
        lambda _settings: FakeClusterCapabilityPort(),
    )

    with pytest.raises(KubernetesPreflightError):
        ensure_scan_execution_backend_available(_settings())


def test_ensure_scan_execution_backend_available_passes_once_config_and_preflight_both_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_selection, "load_kubernetes_config", lambda _settings: None)
    monkeypatch.setattr(
        backend_selection, "_build_cluster_capability", lambda _settings: _ready_capability()
    )

    ensure_scan_execution_backend_available(_settings())  # must not raise


# ---------------------------------------------------------------------------
# create_kubernetes_scan_execution
# ---------------------------------------------------------------------------


def test_create_kubernetes_scan_execution_refuses_when_docker_is_selected() -> None:
    with pytest.raises(KubernetesBackendNotSelectedError):
        create_kubernetes_scan_execution(_settings(backend="docker"), ScannerType.SECRETS)


def test_create_kubernetes_scan_execution_rejects_an_unsupported_scanner_type_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-fast: an unsupported scanner type raises BEFORE the preflight
    ever touches a cluster capability port."""

    def _exploding_capability(_settings: Settings) -> FakeClusterCapabilityPort:
        raise AssertionError(
            "must not build a capability port for an unsupported scanner type"
        )

    monkeypatch.setattr(backend_selection, "_build_cluster_capability", _exploding_capability)

    with pytest.raises(UnsupportedScannerTypeError):
        create_kubernetes_scan_execution(_settings(), ScannerType.SAST)


def test_create_kubernetes_scan_execution_never_touches_the_job_runner_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backend_selection,
        "_build_cluster_capability",
        lambda _settings: FakeClusterCapabilityPort(),
    )
    job_runner = FakeKubernetesJobRunner()
    monkeypatch.setattr(backend_selection, "_build_job_runner", lambda: job_runner)

    with pytest.raises(KubernetesPreflightError):
        create_kubernetes_scan_execution(_settings(), ScannerType.SECRETS)

    assert job_runner.pvc_calls == []
    assert job_runner.job_calls == []
    assert job_runner.delete_job_calls == []
    assert job_runner.delete_pvc_calls == []


def test_create_kubernetes_scan_execution_builds_a_working_bridge_once_preflight_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backend_selection, "_build_cluster_capability", lambda _settings: _ready_capability()
    )
    job_runner = FakeKubernetesJobRunner()
    monkeypatch.setattr(backend_selection, "_build_job_runner", lambda: job_runner)

    execution = create_kubernetes_scan_execution(_settings(), ScannerType.SECRETS)

    assert isinstance(execution, KubernetesRepositoryScanExecution)
    result = execution.execute(
        "https://github.com/example/public-repo.git",
        "main",
        uuid.UUID("11111111-2222-3333-4444-555555555555"),
        ScannerType.SECRETS,
    )
    assert result.findings == []
    # checkout + rev-parse + scanner: the bridge always runs with
    # `scanner_exit_codes_are_data=True` (design D-Result).
    assert len(job_runner.job_calls) == 3
    assert len(job_runner.delete_job_calls) == 3
    assert len(job_runner.delete_pvc_calls) == 1
