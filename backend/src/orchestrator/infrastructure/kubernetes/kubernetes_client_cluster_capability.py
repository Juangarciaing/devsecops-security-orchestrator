"""`KubernetesClientClusterCapability` — `kubernetes` Python client
implementation of `ClusterCapabilityPort` (k8s-backend-enable PR3, design
D-Preflight).

This adapter answers the three fail-closed preflight questions
`validate_kubernetes_preflight` needs, and NEVER classifies a fact as a
`KubernetesPreflightError` itself — every method here returns a plain
`bool`/`StorageClassInfo | None`; `kubernetes_preflight.py` is the ONLY place
that turns "no" into a raised, fail-closed error (mirrors
`KubernetesClientJobRunner`'s "the adapter never classifies" precedent).

`get_storage_class`'s `allowed_access_modes` is a documented, fixed constant
— NOT an API-derived value. `V1StorageClass` genuinely has no access-mode
field (`provisioner`, `volumeBindingMode`, `reclaimPolicy`, `parameters`,
`mountOptions`, `allowedTopologies` — nothing about access modes). A
provisioner-to-access-mode lookup table would be an unbounded, drifting
allowlist; a probe PVC would create a cluster object during preflight,
violating "unproven cluster creates nothing". `ReadWriteOnce` is universally
supported by every provisioner and the only mode this design ever requests.

`network_policies_enforced` treats `kubernetes_cni_enforces_network_policy`
as an operator ATTESTATION the platform cannot itself verify: attestation off
short-circuits with ZERO API calls (cheapest-first, and proves the flag
genuinely gates the check rather than merely influencing its result). When on,
name presence alone is a weak check — the SHAPE matters: `scanner-egress`
must be a genuine total-deny (`Egress` policy type, empty `egress` list).

`namespace_workloads_ready` answers "is this identity permitted to do what
the job runner needs?" via `AuthorizationV1Api.create_self_subject_access_review`
— NOT by reading `Role`/`RoleBinding` objects. `SelfSubjectAccessReview`
answers the real question directly, and the default `system:basic-user`
ClusterRole lets ANY authenticated identity create one, so this preflight
needs no `get roles` grant of its own to run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kubernetes.client import (  # type: ignore[import-untyped]
    ApiException,
    V1ResourceAttributes,
    V1SelfSubjectAccessReview,
    V1SelfSubjectAccessReviewSpec,
)

from orchestrator.domain.ports.kubernetes_preflight_port import (
    ClusterCapabilityPort,
    StorageClassInfo,
)

if TYPE_CHECKING:
    from kubernetes.client import AuthorizationV1Api, CoreV1Api, NetworkingV1Api, StorageV1Api

logger = logging.getLogger(__name__)

_HTTP_NOT_FOUND = 404

#: Design D-Preflight: `V1StorageClass` has no access-mode field at all — see
#: the module docstring for why this is a fixed, documented constant rather
#: than an API-derived value, a provisioner lookup table, or a probe PVC.
_ALLOWED_ACCESS_MODES = frozenset({"ReadWriteOnce"})

#: The two NetworkPolicies `deploy/kubernetes/base/networkpolicies.yaml`
#: renders — `scanner-egress` MUST be a genuine total-deny.
_SCANNER_EGRESS_POLICY_NAME = "scanner-egress"
_CHECKOUT_EGRESS_POLICY_NAME = "checkout-egress"

#: Design D-Preflight / `namespace_workloads_ready`: exactly the verb/resource
#: set `KubernetesJobRunnerPort`'s methods use — `(api_group, resource,
#: subresource, verb)`. MUST match `deploy/kubernetes/base/rbac.yaml`'s
#: `scan-job-runner` Role rules (its own comment: "exactly the Jobs/Pods/PVCs/
#: logs verbs ... never a wildcard").
_REQUIRED_ACCESS_CHECKS: tuple[tuple[str, str, str | None, str], ...] = (
    ("batch", "jobs", None, "create"),
    ("batch", "jobs", None, "get"),
    ("batch", "jobs", None, "delete"),
    ("", "persistentvolumeclaims", None, "create"),
    ("", "persistentvolumeclaims", None, "get"),
    ("", "persistentvolumeclaims", None, "delete"),
    ("", "pods", None, "get"),
    ("", "pods", None, "list"),
    ("", "pods", "log", "get"),
)

#: The two workload ServiceAccounts `deploy/kubernetes/base/serviceaccounts.yaml`
#: renders (`rbac.yaml`'s RoleBindings bind exactly these two).
_WORKLOAD_SERVICE_ACCOUNTS = ("checkout", "scanner")


def _is_not_found(exc: ApiException) -> bool:
    return bool(exc.status == _HTTP_NOT_FOUND)


class KubernetesClientClusterCapability(ClusterCapabilityPort):
    """`kubernetes` Python client adapter over `StorageV1Api`/
    `NetworkingV1Api`/`CoreV1Api`/`AuthorizationV1Api`.

    Takes each typed API client explicitly (mirrors `KubernetesClientJobRunner`'s
    constructor-injection convention) rather than the whole `Settings` object
    — `cni_enforces_network_policy` is the one setting this adapter needs, so
    only that is threaded through, keeping the class trivially mockable.
    """

    def __init__(
        self,
        storage_api: StorageV1Api,
        networking_api: NetworkingV1Api,
        core_api: CoreV1Api,
        authorization_api: AuthorizationV1Api,
        *,
        cni_enforces_network_policy: bool,
    ) -> None:
        self._storage = storage_api
        self._networking = networking_api
        self._core = core_api
        self._authorization = authorization_api
        self._cni_enforces_network_policy = cni_enforces_network_policy

    def get_storage_class(self, name: str) -> StorageClassInfo | None:
        try:
            storage_class = self._storage.read_storage_class(name)
        except ApiException as exc:
            if _is_not_found(exc):
                return None
            raise
        return StorageClassInfo(
            name=name,
            provisioner=storage_class.provisioner,
            volume_binding_mode=storage_class.volume_binding_mode or "Immediate",
            allowed_access_modes=_ALLOWED_ACCESS_MODES,
        )

    def network_policies_enforced(self, namespace: str) -> bool:
        if not self._cni_enforces_network_policy:
            return False
        try:
            policies = self._networking.list_namespaced_network_policy(namespace).items
        except ApiException as exc:
            logger.warning("NetworkPolicy listing failed in %s: %s", namespace, exc.status)
            return False
        by_name = {policy.metadata.name: policy for policy in policies}
        scanner = by_name.get(_SCANNER_EGRESS_POLICY_NAME)
        checkout = by_name.get(_CHECKOUT_EGRESS_POLICY_NAME)
        return (
            scanner is not None
            and "Egress" in (scanner.spec.policy_types or ())
            and not scanner.spec.egress
            and checkout is not None
            and "Egress" in (checkout.spec.policy_types or ())
        )

    def namespace_workloads_ready(self, namespace: str) -> bool:
        try:
            self._core.read_namespace(namespace)
            for service_account_name in _WORKLOAD_SERVICE_ACCOUNTS:
                self._core.read_namespaced_service_account(service_account_name, namespace)
        except ApiException as exc:
            logger.warning(
                "namespace/ServiceAccount check failed in %s: %s", namespace, exc.status
            )
            return False

        for group, resource, subresource, verb in _REQUIRED_ACCESS_CHECKS:
            review = V1SelfSubjectAccessReview(
                spec=V1SelfSubjectAccessReviewSpec(
                    resource_attributes=V1ResourceAttributes(
                        namespace=namespace,
                        group=group,
                        resource=resource,
                        subresource=subresource,
                        verb=verb,
                    )
                )
            )
            try:
                result = self._authorization.create_self_subject_access_review(review)
            except ApiException as exc:
                logger.warning(
                    "SelfSubjectAccessReview failed for %s %s/%s in %s: %s",
                    verb,
                    group,
                    resource,
                    namespace,
                    exc.status,
                )
                return False
            if not result.status.allowed:
                return False
        return True
