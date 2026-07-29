"""RED→GREEN tests for the StorageClass/NetworkPolicy fail-closed preflight
(Module 13c PR7). Per the design's PR7 invariant — "unproven cluster creates
nothing" — `validate_kubernetes_preflight` MUST raise `KubernetesPreflightError`
unless BOTH the configured StorageClass proves it can provision a
`ReadWriteOnce`/`WaitForFirstConsumer` PVC AND NetworkPolicy enforcement is
confirmed in the target namespace. Proven here entirely against
`FakeClusterCapabilityPort` — no live cluster.
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


def test_preflight_succeeds_when_storage_class_and_network_policy_are_both_proven() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_storage_class(_compatible_storage_class())
    port.seed_enforced_namespace(_NAMESPACE)

    result = validate_kubernetes_preflight(
        port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE
    )

    assert result.storage_class_name == _STORAGE_CLASS
    assert result.namespace == _NAMESPACE


def test_preflight_fails_closed_when_storage_class_is_missing() -> None:
    port = FakeClusterCapabilityPort()
    port.seed_enforced_namespace(_NAMESPACE)

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_fails_closed_when_storage_class_does_not_support_read_write_once() -> None:
    port = FakeClusterCapabilityPort()
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
    port.seed_storage_class(_compatible_storage_class())
    # Deliberately NOT seeding the namespace as enforced.

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)


def test_preflight_checks_storage_class_before_network_policy() -> None:
    """Both preconditions are independently fail-closed — a missing
    StorageClass raises even when NetworkPolicy enforcement was never
    configured to succeed either; no ordering/short-circuit bug hides one
    failure behind the other."""
    port = FakeClusterCapabilityPort()

    with pytest.raises(KubernetesPreflightError):
        validate_kubernetes_preflight(port, storage_class_name=_STORAGE_CLASS, namespace=_NAMESPACE)
