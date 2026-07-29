"""Wires `Settings.scan_execution_backend` to the fail-closed Kubernetes
preflight (Module 13c PR8 — closes PR7's SUGGESTION that preflight-gates-
executor was only proven at the unit level).

`create_kubernetes_scan_execution` is the ONLY sanctioned way to obtain a
`KubernetesSplitScanExecution`: it ALWAYS runs `validate_kubernetes_preflight`
first, so `job_runner` is never touched (no PVC/Job submitted) unless the
preflight actually passed (spec/design's "unproven cluster creates nothing").
`ensure_scan_execution_backend_available` is the worker-startup gate — see
`workers/celery_app.py`, which calls it at MODULE-IMPORT time (before Celery
even builds its app object), not from a Celery signal — Celery's own
`Signal.send()` swallows receiver exceptions and logs them rather than
propagating, so a signal-based check alone could never actually fail
startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestrator.infrastructure.kubernetes.kubernetes_preflight import (
    validate_kubernetes_preflight,
)
from orchestrator.infrastructure.kubernetes.kubernetes_scan_execution import (
    KubernetesSplitScanExecution,
)

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_job_runner_port import KubernetesJobRunnerPort
    from orchestrator.domain.ports.kubernetes_preflight_port import ClusterCapabilityPort
    from orchestrator.infrastructure.config.settings import Settings


class KubernetesBackendNotSelectedError(Exception):
    """Raised by `create_kubernetes_scan_execution` when `Settings.scan_execution_backend`
    is not `"kubernetes"` — refuses to build a Kubernetes executor for a
    Docker-selected deployment."""


class KubernetesBackendUnavailableError(Exception):
    """Raised at worker-startup time when `"kubernetes"` is selected but this
    build has no concrete `ClusterCapabilityPort`/`KubernetesJobRunnerPort`
    adapter wired to a real cluster yet. Module 13c PR6/PR7 proved the
    lifecycle and preflight only against fakes (`FakeKubernetesJobRunner`/
    `FakeClusterCapabilityPort`); a live-cluster adapter is deferred behind
    the spec's OPTIONAL kind/k3d proof, not implemented in this slice.
    Failing closed here — rather than silently defaulting to Docker or
    running with tooling that cannot honor "unproven cluster creates
    nothing" — is the only correct behavior until that adapter lands."""


def ensure_scan_execution_backend_available(settings: Settings) -> None:
    """MUST run before any scan work — `workers/celery_app.py` calls this at
    module-import time, which fires before Celery builds `celery_app` and
    long before any task can be consumed.

    Docker (the default/absent-config path) is always a no-op (spec's
    "absent or unsupported configuration MUST use Docker"). Explicitly
    selecting `"kubernetes"` always raises `KubernetesBackendUnavailableError`
    in this build (see that error's docstring for why).
    """
    if settings.scan_execution_backend == "docker":
        return
    raise KubernetesBackendUnavailableError(
        "scan_execution_backend='kubernetes' has no concrete cluster adapter "
        "wired in this build yet; worker startup fails closed rather than "
        "risk a mid-scan Docker fallback"
    )


def create_kubernetes_scan_execution(
    settings: Settings,
    capability_port: ClusterCapabilityPort,
    job_runner: KubernetesJobRunnerPort,
    *,
    scanner_image: str,
    scanner_command: list[str],
) -> KubernetesSplitScanExecution:
    """Validate `settings.scan_execution_backend == "kubernetes"`, run the
    fail-closed preflight, and only then construct a working executor.

    Raises `KubernetesBackendNotSelectedError` when Kubernetes is not
    selected, or `KubernetesPreflightError` (from `validate_kubernetes_preflight`,
    propagated untouched) when the cluster cannot prove PVC/NetworkPolicy
    isolation — in both cases `job_runner` is never called.
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

    result = validate_kubernetes_preflight(
        capability_port,
        storage_class_name=settings.kubernetes_storage_class_name,
        namespace=settings.kubernetes_namespace,
    )
    return KubernetesSplitScanExecution(
        job_runner,
        namespace=result.namespace,
        checkout_image=settings.scan_git_image,
        scanner_image=scanner_image,
        scanner_command=scanner_command,
        timeout_seconds=settings.scan_timeout_seconds,
    )
