"""Live-cluster proof for k8s-backend-enable PR4 (tasks 4.5-4.6) — REAL
`kind-devsecops-orchestrator` API server, no mocks.

Applies `deploy/kubernetes/base/` (idempotent — mirrors the operator step in
`docs/kubernetes-prerequisites.md`), mints a REAL token for the
`scan-orchestrator` ServiceAccount via `kubectl create token`, and builds a
second `ApiClient` authenticated as ONLY that narrow identity (never the
admin kubeconfig identity every other live test in this suite uses).

Confirms, against the real cluster, under the `scan-orchestrator` token:
- `get_storage_class` succeeds — the `storageclasses` rule of the
  `scan-orchestrator-cluster-reader` ClusterRole exception (design D-RBAC)
  genuinely grants cluster-scoped StorageClass read
- `namespace_workloads_ready()` returns `True` end-to-end for the real
  `security-scans` namespace — this identity's own `read_namespace` call is
  granted by that same ClusterRole's `resourceNames`-pinned `namespaces` rule
  (a genuine RBAC requirement: `namespaces` is cluster-scoped even when the
  check is restricted to exactly one namespace's own name), its
  `read_namespaced_service_account` calls are granted by the namespaced
  Role's `serviceaccounts` rule, and every verb/resource pair
  `KubernetesClientClusterCapability.namespace_workloads_ready` checks via
  `SelfSubjectAccessReview` (`_REQUIRED_ACCESS_CHECKS`) is allowed
- `list` on NetworkPolicies (`network_policies_enforced`'s own API call)
  succeeds
- a `SelfSubjectAccessReview` for verbs OUTSIDE the Role/ClusterRole
  (`delete namespaces`, `get secrets`, `get namespaces` for a DIFFERENT
  namespace) is DENIED — proving least privilege, not just presence of the
  in-scope grants

An earlier revision of this file found and documented a genuine gap here —
the Role as first scoped by tasks 4.1-4.4 granted nothing on `namespaces` or
`serviceaccounts`, so `namespace_workloads_ready()` 403'd under the real
token even though every individual access-review check passed. That gap was
closed by extending `orchestrator-rbac.yaml` (the `serviceaccounts` rule on
the namespaced Role, and the `resourceNames`-pinned `namespaces` rule on the
ClusterRole) rather than left as deferred debt — see git history for the
before/after.

Skips automatically if `kind-devsecops-orchestrator` is not reachable —
mirrors `test_kubernetes_client_cluster_capability_live.py`'s convention.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from kubernetes import client as k8s_client

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_cluster_capability import (
    _REQUIRED_ACCESS_CHECKS,
    KubernetesClientClusterCapability,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"
_SERVICE_ACCOUNT = "scan-orchestrator"

#: (group, resource, subresource, verb, resource_name) — genuinely denied
#: even after the RBAC fix. `("", "namespaces", None, "get", "default")`
#: proves the ClusterRole's `resourceNames` pinning is real: this identity
#: can `get` its OWN namespace by name, never any other.
_OUT_OF_SCOPE_CHECKS: tuple[tuple[str, str, str | None, str, str | None], ...] = (
    ("", "namespaces", None, "delete", _NAMESPACE),
    ("", "namespaces", None, "get", "default"),
    ("", "secrets", None, "get", None),
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://o:o@localhost/o",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        kubernetes_kubeconfig_context=_CONTEXT,
    )


@pytest.fixture(scope="module")
def orchestrator_rbac_api_client() -> Iterator[k8s_client.ApiClient]:
    """Applies the base kustomization, mints a token for the real
    `scan-orchestrator` ServiceAccount, and builds an `ApiClient` scoped to
    ONLY that identity — never the admin kubeconfig identity."""
    try:
        load_kubernetes_config(_settings())
        k8s_client.CoreV1Api().list_namespace(_request_timeout=5)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"kind-devsecops-orchestrator cluster not reachable: {exc}")

    repo_root = __file__.rsplit("/backend/", 1)[0]
    subprocess.run(
        ["kubectl", "apply", "-k", f"{repo_root}/deploy/kubernetes/base/"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    token = subprocess.run(
        ["kubectl", "create", "token", _SERVICE_ACCOUNT, "-n", _NAMESPACE, "--duration=10m"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()

    admin_config = k8s_client.Configuration.get_default_copy()
    token_config = k8s_client.Configuration()
    token_config.host = admin_config.host
    token_config.ssl_ca_cert = admin_config.ssl_ca_cert
    token_config.api_key = {"authorization": f"Bearer {token}"}
    yield k8s_client.ApiClient(configuration=token_config)


def _self_subject_access_review(
    authorization_api: k8s_client.AuthorizationV1Api,
    *,
    group: str,
    resource: str,
    subresource: str | None,
    verb: str,
    namespace: str | None = _NAMESPACE,
    name: str | None = None,
) -> bool:
    review = k8s_client.V1SelfSubjectAccessReview(
        spec=k8s_client.V1SelfSubjectAccessReviewSpec(
            resource_attributes=k8s_client.V1ResourceAttributes(
                namespace=namespace,
                group=group,
                resource=resource,
                subresource=subresource,
                verb=verb,
                name=name,
            )
        )
    )
    return bool(authorization_api.create_self_subject_access_review(review).status.allowed)


def test_scan_orchestrator_token_reads_the_real_storage_class(
    orchestrator_rbac_api_client: k8s_client.ApiClient,
) -> None:
    """Proves the `storageclasses` rule of the `scan-orchestrator-cluster-
    reader` ClusterRole exception genuinely grants cluster-scoped
    StorageClass read to ONLY the `scan-orchestrator` identity's own
    token."""
    storage_api = k8s_client.StorageV1Api(orchestrator_rbac_api_client)

    storage_class = storage_api.read_storage_class(_STORAGE_CLASS)

    assert storage_class.provisioner == "rancher.io/local-path"


def test_scan_orchestrator_token_lists_networkpolicies(
    orchestrator_rbac_api_client: k8s_client.ApiClient,
) -> None:
    networking_api = k8s_client.NetworkingV1Api(orchestrator_rbac_api_client)

    names = {
        policy.metadata.name
        for policy in networking_api.list_namespaced_network_policy(_NAMESPACE).items
    }

    assert {"checkout-egress", "scanner-egress"} <= names


def test_scan_orchestrator_token_is_allowed_every_jobrunner_verb(
    orchestrator_rbac_api_client: k8s_client.ApiClient,
) -> None:
    """Every verb/resource pair `namespace_workloads_ready` checks via
    `SelfSubjectAccessReview` — the exact set the real JobRunner adapter
    uses — must be allowed under the real `scan-orchestrator` Role."""
    authorization_api = k8s_client.AuthorizationV1Api(orchestrator_rbac_api_client)

    for group, resource, subresource, verb in _REQUIRED_ACCESS_CHECKS:
        allowed = _self_subject_access_review(
            authorization_api, group=group, resource=resource, subresource=subresource, verb=verb
        )
        assert allowed, f"expected {verb} {group}/{resource} to be allowed"


def test_scan_orchestrator_token_is_denied_verbs_outside_the_role(
    orchestrator_rbac_api_client: k8s_client.ApiClient,
) -> None:
    """`delete namespaces` (any name), `get namespaces` for a DIFFERENT
    namespace than `security-scans`, and `get secrets` are all outside the
    `scan-orchestrator` Role/ClusterRole grant — a real
    `SelfSubjectAccessReview` must deny every one of them. The `namespaces`
    case in particular proves the ClusterRole's `resourceNames` pinning is
    real, not merely present in the manifest."""
    authorization_api = k8s_client.AuthorizationV1Api(orchestrator_rbac_api_client)

    for group, resource, subresource, verb, name in _OUT_OF_SCOPE_CHECKS:
        allowed = _self_subject_access_review(
            authorization_api,
            group=group,
            resource=resource,
            subresource=subresource,
            verb=verb,
            namespace=None,
            name=name,
        )
        assert not allowed, f"expected {verb} {resource} (name={name!r}) to be denied"


def test_namespace_workloads_ready_succeeds_end_to_end_under_the_real_orchestrator_token(
    orchestrator_rbac_api_client: k8s_client.ApiClient,
) -> None:
    """The strongest possible proof: builds the REAL
    `KubernetesClientClusterCapability` adapter using ONLY the
    `scan-orchestrator` token's API clients and calls
    `namespace_workloads_ready` exactly as `kubernetes_preflight.py` would in
    production. An earlier revision of this file found this 403'd — the
    `serviceaccounts` rule (namespaced Role) and the `resourceNames`-pinned
    `namespaces` rule (ClusterRole) added to `orchestrator-rbac.yaml` close
    that gap; this test proves the fix, end-to-end, against the real
    cluster."""
    capability = KubernetesClientClusterCapability(
        k8s_client.StorageV1Api(orchestrator_rbac_api_client),
        k8s_client.NetworkingV1Api(orchestrator_rbac_api_client),
        k8s_client.CoreV1Api(orchestrator_rbac_api_client),
        k8s_client.AuthorizationV1Api(orchestrator_rbac_api_client),
        cni_enforces_network_policy=True,
    )

    assert capability.namespace_workloads_ready(_NAMESPACE) is True
