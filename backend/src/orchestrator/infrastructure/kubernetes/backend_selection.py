"""Wires `Settings.scan_execution_backend` to the REAL, live-cluster
Kubernetes preflight and routing (k8s-backend-enable PR6, design D-Routing).

This is the ONLY slice in the k8s-backend-enable chain where the
unconditional fail-closed raise is replaced with a genuine cluster check —
design D5's hard invariant: the raise dies in exactly this slice, together
with `workers/tasks/process_scan.py`'s live routing branch, never separately.

`create_kubernetes_scan_execution` is the ONLY sanctioned way to obtain a
working Kubernetes executor: it ALWAYS runs `validate_kubernetes_preflight`
first (building its own `ClusterCapabilityPort`/`KubernetesJobRunnerPort`
from live `kubernetes` API clients), so no PVC/Job is ever submitted unless
the preflight actually passed (spec/design's "unproven cluster creates
nothing"), and it returns the PR5 `KubernetesRepositoryScanExecution` bridge
— a real `ScanExecutionPort` — rather than the lower-level split executor.
`ensure_scan_execution_backend_available` is the worker-startup gate — see
`workers/celery_app.py`, which calls it at MODULE-IMPORT time (before Celery
even builds its app object), not from a Celery signal — Celery's own
`Signal.send()` swallows receiver exceptions and logs them rather than
propagating, so a signal-based check alone could never actually fail
startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kubernetes import client as k8s_client  # type: ignore[import-untyped]

from orchestrator.infrastructure.kubernetes.kubernetes_client_cluster_capability import (
    KubernetesClientClusterCapability,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_job_runner import (
    KubernetesClientJobRunner,
)
from orchestrator.infrastructure.kubernetes.kubernetes_preflight import (
    validate_kubernetes_preflight,
)
from orchestrator.infrastructure.kubernetes.kubernetes_repository_scan_execution import (
    KubernetesRepositoryScanExecution,
)
from orchestrator.infrastructure.kubernetes.kubernetes_scanner_descriptor import (
    resolve_kubernetes_scanner,
)

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_job_runner_port import KubernetesJobRunnerPort
    from orchestrator.domain.ports.kubernetes_preflight_port import ClusterCapabilityPort
    from orchestrator.domain.value_objects.enums import ScannerType
    from orchestrator.infrastructure.config.settings import Settings


class KubernetesBackendNotSelectedError(Exception):
    """Raised by `create_kubernetes_scan_execution` when `Settings.scan_execution_backend`
    is not `"kubernetes"` — refuses to build a Kubernetes executor for a
    Docker-selected deployment."""


class KubernetesBackendUnavailableError(Exception):
    """Raised at worker-startup time when `"kubernetes"` is selected but this
    build's Kubernetes client CONFIGURATION cannot be loaded (design
    D-Routing) — e.g. no reachable kubeconfig context, no in-cluster
    ServiceAccount token, or a malformed kubeconfig file. This wraps
    `load_kubernetes_config`'s own failure ONLY: once configuration loads
    successfully, a genuine preflight failure (missing namespace/RBAC/
    StorageClass/NetworkPolicy enforcement) raises `KubernetesPreflightError`
    directly, untouched — that is a DIFFERENT, more specific failure the
    caller should be able to distinguish. Failing closed here — rather than
    silently defaulting to Docker or running with tooling that cannot honor
    "unproven cluster creates nothing" — is the only correct behavior."""


def ensure_scan_execution_backend_available(settings: Settings) -> None:
    """MUST run before any scan work — `workers/celery_app.py` calls this at
    module-import time, which fires before Celery builds `celery_app` and
    long before any task can be consumed.

    Docker (the default/absent-config path) is always a no-op (spec's
    "absent or unsupported configuration MUST use Docker"). Explicitly
    selecting `"kubernetes"` loads the real client configuration
    (`load_kubernetes_config`, in-cluster-first — design D-Client) and then
    runs the REAL fail-closed preflight (design D-Preflight) against a
    freshly built `KubernetesClientClusterCapability`. A config-load failure
    raises `KubernetesBackendUnavailableError`; a preflight failure raises
    `KubernetesPreflightError` untouched (see that error's own docstring for
    the fail-closed contract) — either way, worker startup fails closed
    rather than risk a mid-scan Docker fallback (design D5: the raise dies
    ONLY here, together with `process_scan.py`'s routing branch).
    """
    if settings.scan_execution_backend == "docker":
        return
    # Settings' own model_validator enforces this pairing whenever
    # scan_execution_backend == "kubernetes" — guaranteed non-None here.
    assert settings.kubernetes_namespace is not None
    assert settings.kubernetes_storage_class_name is not None

    try:
        load_kubernetes_config(settings)
    except Exception as exc:
        raise KubernetesBackendUnavailableError(
            f"failed to load Kubernetes client configuration: {exc}"
        ) from exc

    validate_kubernetes_preflight(
        _build_cluster_capability(settings),
        storage_class_name=settings.kubernetes_storage_class_name,
        namespace=settings.kubernetes_namespace,
    )


def _build_cluster_capability(settings: Settings) -> ClusterCapabilityPort:
    """Construct a `KubernetesClientClusterCapability` over fresh, default-
    configured `kubernetes` client API objects — mirrors the construction
    pattern already proven live by this chain's own integration tests
    (`test_kubernetes_client_cluster_capability_live.py`). Requires
    `load_kubernetes_config`/`kubernetes.config.load_*` to have already run
    in this process (the client library keeps its active configuration as
    global, ambient state)."""
    return KubernetesClientClusterCapability(
        k8s_client.StorageV1Api(),
        k8s_client.NetworkingV1Api(),
        k8s_client.CoreV1Api(),
        k8s_client.AuthorizationV1Api(),
        cni_enforces_network_policy=settings.kubernetes_cni_enforces_network_policy,
    )


def _build_job_runner() -> KubernetesJobRunnerPort:
    """Construct a `KubernetesClientJobRunner` over fresh, default-configured
    `kubernetes` client API objects — same ambient-configuration precondition
    as `_build_cluster_capability`."""
    return KubernetesClientJobRunner(k8s_client.BatchV1Api(), k8s_client.CoreV1Api())


def create_kubernetes_scan_execution(
    settings: Settings, scanner_type: ScannerType
) -> KubernetesRepositoryScanExecution:
    """Validate `settings.scan_execution_backend == "kubernetes"`, run the
    fail-closed preflight against a FRESH, live cluster capability port, and
    only then construct a working `ScanExecutionPort` bridge.

    Unlike the pre-PR6 signature, this no longer takes a capability port,
    job runner, scanner image, or scanner command as arguments — it builds
    its own `KubernetesClientClusterCapability`/`KubernetesClientJobRunner`
    from live `kubernetes` API clients (design D-Routing: "constructs its own
    capability port and job runner from settings"), and resolves
    `scanner_type` via `resolve_kubernetes_scanner` up front — fail-fast on an
    unsupported scanner type BEFORE any preflight API call, so no wasted
    cluster round-trip precedes a guaranteed `UnsupportedScannerTypeError`.
    The actual image/argv resolution the bridge NEEDS happens again, inside
    `KubernetesRepositoryScanExecution.execute()` itself, per call — this
    up-front resolution exists purely for the early, cheap fail-fast.

    Raises `KubernetesBackendNotSelectedError` when Kubernetes is not
    selected (guard UNCHANGED from before PR6), `UnsupportedScannerTypeError`
    (from `resolve_kubernetes_scanner`) for a scanner type this backend does
    not support, or `KubernetesPreflightError` (from
    `validate_kubernetes_preflight`, propagated untouched) when the cluster
    cannot prove namespace/RBAC/StorageClass/NetworkPolicy isolation — in
    every failure case, no job runner is ever constructed and no PVC/Job is
    ever submitted.
    """
    if settings.scan_execution_backend != "kubernetes":
        raise KubernetesBackendNotSelectedError(
            "scan_execution_backend is not 'kubernetes'; refusing to build a "
            "Kubernetes executor"
        )
    # Settings' own model_validator enforces this pairing whenever
    # scan_execution_backend == "kubernetes" — guaranteed non-None here.
    assert settings.kubernetes_namespace is not None
    assert settings.kubernetes_storage_class_name is not None

    resolve_kubernetes_scanner(scanner_type, settings)

    result = validate_kubernetes_preflight(
        _build_cluster_capability(settings),
        storage_class_name=settings.kubernetes_storage_class_name,
        namespace=settings.kubernetes_namespace,
    )
    return KubernetesRepositoryScanExecution(
        _build_job_runner(),
        namespace=result.namespace,
        checkout_image=settings.scan_git_image,
        settings=settings,
        timeout_seconds=settings.scan_timeout_seconds,
    )
