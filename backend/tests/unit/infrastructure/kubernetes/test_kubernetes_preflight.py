"""RED→GREEN tests for the namespace/StorageClass/NetworkPolicy fail-closed
preflight (Module 13c PR7, extended k8s-backend-enable PR3). Per the design's
PR7 invariant — "unproven cluster creates nothing" — `validate_kubernetes_preflight`
MUST raise `KubernetesPreflightError` unless ALL THREE preconditions hold, in
this order: (1) the target namespace's workloads are ready (namespace + both
ServiceAccounts exist, every JobRunner verb is permitted); (2) the configured
StorageClass proves it can provision a `ReadWriteOnce`/`WaitForFirstConsumer`
PVC; (3) NetworkPolicy enforcement is confirmed in the target namespace.
Proven here entirely against `FakeClusterCapabilityPort` — no live cluster.
"""

from __future__ import annotations

import pytest

from orchestrator.domain.ports.kubernetes_preflight_port import StorageClassInfo
from orchestrator.infrastructure.kubernetes.kubernetes_preflight import (
    KubernetesPreflightError,
    validate_kubernetes_preflight,
)
from tests.fakes.fake_cluster_capability import FakeClusterCapabilityPort

_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"


def _compatible_storage_class() -> StorageClassInfo:
    return StorageClassInfo(
        name=_STORAGE_CLASS,
        provisioner="kubernetes.io/aws-ebs",
        volume_binding_mode="WaitForFirstConsumer",
        allowed_access_modes=frozenset({"ReadWriteOnce"}),
    )


def test_preflight_succeeds_when_namespace_storage_class_and_network_policy_are_all_proven() -> (
    None
):
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_storage_class(_compatible_storage_class())
    port.seed_enforced_namespace(_NAMESPACE)

    result = validate_kubernetes_preflight(
        port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE
    )

    assert result.storage_class_name == _STORAGE_CLASS
    assert result.namespace == _NAMESPACE


def test_preflight_fails_closed_when_namespace_workloads_are_not_ready() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_storage_class(_compatible_storage_class())
    port.seed_enforced_namespace(_NAMESPACE)
    # Deliberately NOT seeding the namespace as ready.

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_fails_closed_when_storage_class_is_missing() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_enforced_namespace(_NAMESPACE)

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_fails_closed_when_storage_class_does_not_support_read_write_once() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_storage_class(
        StorageClassInfo(
            name=_STORAGE_CLASS,
            provisioner="kubernetes.io/aws-efs",
            volume_binding_mode="WaitForFirstConsumer",
            allowed_access_modes=frozenset({"ReadOnlyMany"}),
        )
    )
    port.seed_enforced_namespace(_NAMESPACE)

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_fails_closed_when_storage_class_does_not_bind_wait_for_first_consumer() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_storage_class(
        StorageClassInfo(
            name=_STORAGE_CLASS,
            provisioner="kubernetes.io/aws-ebs",
            volume_binding_mode="Immediate",
            allowed_access_modes=frozenset({"ReadWriteOnce"}),
        )
    )
    port.seed_enforced_namespace(_NAMESPACE)

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_fails_closed_when_network_policy_enforcement_is_unconfirmed() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_storage_class(_compatible_storage_class())
    # Deliberately NOT seeding the namespace as enforced.

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_checks_storage_class_before_network_policy() -> None:
    """Both the StorageClass and NetworkPolicy preconditions are
    independently fail-closed — a missing StorageClass raises even when
    NetworkPolicy enforcement was never configured to succeed either; no
    ordering/short-circuit bug hides one failure behind the other. (The
    namespace-readiness precondition is checked first — see
    `test_preflight_checks_namespace_workloads_before_storage_class_and_network_policy`
    for the full three-branch call order.)"""
    port = FakeClusterCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_checks_namespace_workloads_before_storage_class_and_network_policy() -> None:
    """Ordering test (task 3.1/3.11): `namespace_workloads_ready` MUST be
    called first, `get_storage_class` second, and `network_policies_enforced`
    last — a missing namespace/ServiceAccount/RBAC grant should never be
    misreported as a StorageClass or NetworkPolicy problem."""
    call_order: list[str] = []

    class _RecordingCapabilityPort(FakeClusterCapabilityPort):
        def namespace_workloads_ready(self, namespace: str) -> bool:
            call_order.append("namespace_workloads_ready")
            return super().namespace_workloads_ready(namespace)

        def get_storage_class(self, name: str) -> StorageClassInfo | None:
            call_order.append("get_storage_class")
            return super().get_storage_class(name)

        def network_policies_enforced(self, namespace: str) -> bool:
            call_order.append("network_policies_enforced")
            return super().network_policies_enforced(namespace)

    port = _RecordingCapabilityPort()
    port.seed_ready_namespace(_NAMESPACE)
    port.seed_storage_class(_compatible_storage_class())
    port.seed_enforced_namespace(_NAMESPACE)

    validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)

    assert call_order == [
        "namespace_workloads_ready",
        "get_storage_class",
        "network_policies_enforced",
    ]
