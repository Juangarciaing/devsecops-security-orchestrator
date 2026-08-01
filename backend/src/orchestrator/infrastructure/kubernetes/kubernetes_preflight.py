"""Fail-closed StorageClass/NetworkPolicy preflight (Module 13c PR7).

Runs at settings/validation time — NEVER at manifest-apply/Job-submission
time. Per the design's PR7 invariant ("unproven cluster creates nothing"),
callers MUST invoke `validate_kubernetes_preflight` and let it succeed
BEFORE ever considering the Kubernetes backend available/selectable, and
BEFORE `KubernetesSplitScanExecution` (PR6) ever submits a PVC or Job.

Wiring this result into actual backend selection/settings toggles is PR8 —
this module only proves the check itself is correct and fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_preflight_port import ClusterCapabilityPort

#: MUST match `PvcSpec`'s defaults (`domain.ports.kubernetes_job_runner_port`)
#: — the preflight proves the cluster can satisfy exactly the PVC shape
#: `KubernetesSplitScanExecution` actually requests, nothing broader.
_REQUIRED_ACCESS_MODE = "ReadWriteOnce"
_REQUIRED_BINDING_MODE = "WaitForFirstConsumer"


class KubernetesPreflightError(Exception):
    """Fail-closed: the cluster cannot prove PVC provisioning or
    NetworkPolicy enforcement. Kubernetes MUST NOT be considered
    available/selectable while this is raised — no Job or PVC is ever
    submitted on this path (design's "unproven cluster creates nothing")."""


@dataclass(frozen=True, slots=True)
class KubernetesPreflightResult:
    """Proof that `storage_class_name`/`namespace` passed the preflight."""

    storage_class_name: str
    namespace: str


def validate_kubernetes_preflight(
    capability_port: ClusterCapabilityPort,
    *,
    storage_class_name: str,
    namespace: str,
) -> KubernetesPreflightResult:
    """Raise `KubernetesPreflightError` unless ALL THREE preconditions hold,
    checked in this order:

    1. `namespace`'s workloads are ready — the namespace and both workload
       ServiceAccounts exist, and this identity is permitted every verb the
       job runner uses (k8s-backend-enable PR3, design D-Preflight). Checked
       FIRST so a missing namespace/ServiceAccount/RBAC grant is never
       misreported as a StorageClass or NetworkPolicy problem.
    2. `storage_class_name` exists, supports `ReadWriteOnce` access, and
       binds `WaitForFirstConsumer` (matching `PvcSpec`'s defaults — spec:
       "Split Public-Repository PVC Workspace").
    3. NetworkPolicy enforcement is confirmed in `namespace` (spec:
       "Missing ... NetworkPolicy enforcement MUST make Kubernetes
       unavailable/fail closed").

    Each precondition is checked independently — a missing StorageClass
    raises even if NetworkPolicy enforcement was never seeded either;
    nothing here short-circuits into a misleading error.
    """
    if not capability_port.namespace_workloads_ready(namespace):
        raise KubernetesPreflightError(
            f"namespace {namespace!r} is not ready for Kubernetes workloads "
            "(missing namespace, ServiceAccount, or insufficient RBAC) — "
            "Kubernetes is unavailable"
        )

    storage_class = capability_port.get_storage_class(storage_class_name)
    if storage_class is None:
        raise KubernetesPreflightError(
            f"StorageClass {storage_class_name!r} was not found — Kubernetes is unavailable"
        )
    if _REQUIRED_ACCESS_MODE not in storage_class.allowed_access_modes:
        raise KubernetesPreflightError(
            f"StorageClass {storage_class_name!r} does not support "
            f"{_REQUIRED_ACCESS_MODE} — Kubernetes is unavailable"
        )
    if storage_class.volume_binding_mode != _REQUIRED_BINDING_MODE:
        raise KubernetesPreflightError(
            f"StorageClass {storage_class_name!r} does not use "
            f"{_REQUIRED_BINDING_MODE} volume binding — Kubernetes is unavailable"
        )

    if not capability_port.network_policies_enforced(namespace):
        raise KubernetesPreflightError(
            f"NetworkPolicy enforcement could not be confirmed in namespace "
            f"{namespace!r} — Kubernetes is unavailable"
        )

    return KubernetesPreflightResult(storage_class_name=storage_class_name, namespace=namespace)
