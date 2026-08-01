"""`KubernetesClientClusterCapability` — mocked-API-client unit tests
(k8s-backend-enable PR3, tasks 3.4-3.8, design D-Preflight).

Mirrors `test_kubernetes_client_job_runner.py`'s convention: these tests only
prove the `kubernetes` client is invoked with the RIGHT arguments and that the
adapter maps 404/attestation-off/tampered-policy/denied-RBAC shapes correctly
— never raising into the fail-closed preflight. Live-cluster proof that
attestation-off genuinely makes zero API calls, that a live tampered
`scanner-egress` is rejected, and that the real `scan-workspace` StorageClass
reports its real shape lives in
`tests/integration/test_kubernetes_client_cluster_capability_live.py` (task
3.12).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client import ApiException  # type: ignore[import-untyped]

from orchestrator.infrastructure.kubernetes.kubernetes_client_cluster_capability import (
    KubernetesClientClusterCapability,
)

_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"

#: Design D-Preflight / `namespace_workloads_ready`: exactly the verb/resource
#: set `KubernetesJobRunnerPort`'s methods use — matches
#: `deploy/kubernetes/base/rbac.yaml`'s `scan-job-runner` Role's own comment
#: ("exactly the Jobs/Pods/PVCs/logs verbs ... never a wildcard").
_EXPECTED_ACCESS_CHECKS = {
    ("batch", "jobs", None, "create"),
    ("batch", "jobs", None, "get"),
    ("batch", "jobs", None, "delete"),
    ("", "persistentvolumeclaims", None, "create"),
    ("", "persistentvolumeclaims", None, "get"),
    ("", "persistentvolumeclaims", None, "delete"),
    ("", "pods", None, "get"),
    ("", "pods", None, "list"),
    ("", "pods", "log", "get"),
}


def _api_exception(status: int) -> ApiException:
    return ApiException(status=status)


def _capability(
    *,
    cni_enforces_network_policy: bool = True,
    storage_api: MagicMock | None = None,
    networking_api: MagicMock | None = None,
    core_api: MagicMock | None = None,
    authorization_api: MagicMock | None = None,
) -> tuple[KubernetesClientClusterCapability, MagicMock, MagicMock, MagicMock, MagicMock]:
    storage = storage_api if storage_api is not None else MagicMock()
    networking = networking_api if networking_api is not None else MagicMock()
    core = core_api if core_api is not None else MagicMock()
    authorization = authorization_api if authorization_api is not None else MagicMock()
    capability = KubernetesClientClusterCapability(
        storage,
        networking,
        core,
        authorization,
        cni_enforces_network_policy=cni_enforces_network_policy,
    )
    return capability, storage, networking, core, authorization


def _network_policy(
    name: str, *, policy_types: list[str], egress: list[object] | None
) -> MagicMock:
    policy = MagicMock()
    policy.metadata.name = name
    policy.spec.policy_types = policy_types
    policy.spec.egress = egress
    return policy


def _allowed_review() -> MagicMock:
    review = MagicMock()
    review.status.allowed = True
    return review


def _denied_review() -> MagicMock:
    review = MagicMock()
    review.status.allowed = False
    return review


def _seed_ready_core(core: MagicMock) -> None:
    """Namespace + both workload ServiceAccounts exist — the shared
    `namespace_workloads_ready` precondition every access-review test below
    builds on."""
    core.read_namespace.return_value = MagicMock()
    core.read_namespaced_service_account.return_value = MagicMock()


# ---------------------------------------------------------------------------
# 3.4 get_storage_class
# ---------------------------------------------------------------------------


def test_get_storage_class_returns_none_on_404() -> None:
    capability, storage, *_rest = _capability()
    storage.read_storage_class.side_effect = _api_exception(404)

    assert capability.get_storage_class(_STORAGE_CLASS) is None


def test_get_storage_class_reraises_non_404() -> None:
    capability, storage, *_rest = _capability()
    storage.read_storage_class.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        capability.get_storage_class(_STORAGE_CLASS)


def test_get_storage_class_maps_provisioner_and_binding_mode() -> None:
    capability, storage, *_rest = _capability()
    storage.read_storage_class.return_value = MagicMock(
        provisioner="kubernetes.io/aws-ebs", volume_binding_mode="WaitForFirstConsumer"
    )

    info = capability.get_storage_class(_STORAGE_CLASS)

    assert info is not None
    assert info.name == _STORAGE_CLASS
    assert info.provisioner == "kubernetes.io/aws-ebs"
    assert info.volume_binding_mode == "WaitForFirstConsumer"


def test_get_storage_class_defaults_missing_binding_mode_to_immediate() -> None:
    capability, storage, *_rest = _capability()
    storage.read_storage_class.return_value = MagicMock(
        provisioner="kubernetes.io/aws-ebs", volume_binding_mode=None
    )

    info = capability.get_storage_class(_STORAGE_CLASS)

    assert info is not None
    assert info.volume_binding_mode == "Immediate"


def test_get_storage_class_allowed_access_modes_is_the_documented_constant_not_probed() -> None:
    """Design D-Preflight: `V1StorageClass` has no access-mode field at
    all — this MUST be a fixed, documented constant, never a provisioner
    lookup table or a probe PVC (both rejected by the design)."""
    capability, storage, *_rest = _capability()
    storage.read_storage_class.return_value = MagicMock(
        provisioner="some.exotic/csi-driver", volume_binding_mode="WaitForFirstConsumer"
    )

    info = capability.get_storage_class(_STORAGE_CLASS)

    assert info is not None
    assert info.allowed_access_modes == frozenset({"ReadWriteOnce"})


# ---------------------------------------------------------------------------
# 3.5-3.7 network_policies_enforced
# ---------------------------------------------------------------------------


def test_network_policies_enforced_short_circuits_when_attestation_is_off() -> None:
    capability, _storage, networking, *_rest = _capability(cni_enforces_network_policy=False)

    assert capability.network_policies_enforced(_NAMESPACE) is False
    networking.list_namespaced_network_policy.assert_not_called()


def test_network_policies_enforced_true_when_both_policies_prove_the_right_shape() -> None:
    capability, _storage, networking, *_rest = _capability(cni_enforces_network_policy=True)
    networking.list_namespaced_network_policy.return_value = MagicMock(
        items=[
            _network_policy("scanner-egress", policy_types=["Egress"], egress=[]),
            _network_policy("checkout-egress", policy_types=["Egress"], egress=[MagicMock()]),
        ]
    )

    assert capability.network_policies_enforced(_NAMESPACE) is True


def test_network_policies_enforced_false_when_scanner_egress_is_not_total_deny() -> None:
    """`scanner-egress` PRESENT is not enough — its `egress` list must be
    EMPTY (total deny); a non-empty egress list is exactly the
    tampered/misconfigured shape this check exists to catch."""
    capability, _storage, networking, *_rest = _capability(cni_enforces_network_policy=True)
    networking.list_namespaced_network_policy.return_value = MagicMock(
        items=[
            _network_policy("scanner-egress", policy_types=["Egress"], egress=[MagicMock()]),
            _network_policy("checkout-egress", policy_types=["Egress"], egress=[MagicMock()]),
        ]
    )

    assert capability.network_policies_enforced(_NAMESPACE) is False


def test_network_policies_enforced_false_when_a_required_policy_is_missing() -> None:
    capability, _storage, networking, *_rest = _capability(cni_enforces_network_policy=True)
    networking.list_namespaced_network_policy.return_value = MagicMock(
        items=[_network_policy("scanner-egress", policy_types=["Egress"], egress=[])]
    )

    assert capability.network_policies_enforced(_NAMESPACE) is False


def test_network_policies_enforced_false_and_never_raises_on_api_exception() -> None:
    capability, _storage, networking, *_rest = _capability(cni_enforces_network_policy=True)
    networking.list_namespaced_network_policy.side_effect = _api_exception(500)

    assert capability.network_policies_enforced(_NAMESPACE) is False


# ---------------------------------------------------------------------------
# 3.8 namespace_workloads_ready
# ---------------------------------------------------------------------------


def test_namespace_workloads_ready_true_when_ns_service_accounts_and_every_verb_are_allowed() -> (
    None
):
    capability, _storage, _networking, core, authorization = _capability()
    _seed_ready_core(core)
    authorization.create_self_subject_access_review.return_value = _allowed_review()

    assert capability.namespace_workloads_ready(_NAMESPACE) is True
    core.read_namespaced_service_account.assert_any_call("checkout", _NAMESPACE)
    core.read_namespaced_service_account.assert_any_call("scanner", _NAMESPACE)


def test_namespace_workloads_ready_false_when_namespace_is_missing() -> None:
    capability, _storage, _networking, core, authorization = _capability()
    core.read_namespace.side_effect = _api_exception(404)

    assert capability.namespace_workloads_ready(_NAMESPACE) is False
    authorization.create_self_subject_access_review.assert_not_called()


def test_namespace_workloads_ready_false_when_a_service_account_is_missing() -> None:
    capability, _storage, _networking, core, authorization = _capability()
    core.read_namespace.return_value = MagicMock()
    core.read_namespaced_service_account.side_effect = _api_exception(404)

    assert capability.namespace_workloads_ready(_NAMESPACE) is False
    authorization.create_self_subject_access_review.assert_not_called()


def test_namespace_workloads_ready_false_when_any_verb_is_denied() -> None:
    capability, _storage, _networking, core, authorization = _capability()
    _seed_ready_core(core)
    authorization.create_self_subject_access_review.side_effect = [
        _allowed_review(),
        _denied_review(),
    ]

    assert capability.namespace_workloads_ready(_NAMESPACE) is False


def test_namespace_workloads_ready_false_and_never_raises_when_access_review_call_fails() -> None:
    capability, _storage, _networking, core, authorization = _capability()
    _seed_ready_core(core)
    authorization.create_self_subject_access_review.side_effect = _api_exception(403)

    assert capability.namespace_workloads_ready(_NAMESPACE) is False


def test_namespace_workloads_ready_checks_the_exact_job_runner_verb_resource_set() -> None:
    """Design D-Preflight: `create`/`get`/`delete` on `batch/jobs` and
    `persistentvolumeclaims`, `get`/`list` on `pods`, `get` on `pods/log` —
    exactly the verbs `KubernetesJobRunnerPort`'s methods use, nothing
    broader (mirrors `deploy/kubernetes/base/rbac.yaml`'s own comment)."""
    capability, _storage, _networking, core, authorization = _capability()
    _seed_ready_core(core)
    authorization.create_self_subject_access_review.return_value = _allowed_review()

    capability.namespace_workloads_ready(_NAMESPACE)

    reviewed = {
        (
            call.args[0].spec.resource_attributes.group,
            call.args[0].spec.resource_attributes.resource,
            call.args[0].spec.resource_attributes.subresource,
            call.args[0].spec.resource_attributes.verb,
        )
        for call in authorization.create_self_subject_access_review.call_args_list
    }
    assert reviewed == _EXPECTED_ACCESS_CHECKS
    assert all(
        call.args[0].spec.resource_attributes.namespace == _NAMESPACE
        for call in authorization.create_self_subject_access_review.call_args_list
    )
