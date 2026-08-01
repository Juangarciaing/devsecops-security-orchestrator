"""Live-cluster proof for k8s-backend-enable PR3 (task 3.12) — REAL
`kind-devsecops-orchestrator` API server, no mocks.

Confirms, against the real cluster:
- attestation off (`cni_enforces_network_policy=False`) fails
  `network_policies_enforced` closed with ZERO API calls, proven by making the
  real `NetworkingV1Api` client explode if it is ever invoked
- the real `scan-workspace` StorageClass reports its real
  provisioner/`WaitForFirstConsumer` shape via `get_storage_class`, and a
  StorageClass that does not exist returns `None`
- `namespace_workloads_ready` reports `True` for the real `security-scans`
  namespace (its `checkout`/`scanner` ServiceAccounts and `scan-job-runner`
  Role/RoleBindings were applied during the PR2 apply batch) and `False` for
  a namespace that does not exist
- `network_policies_enforced` reports `True` against the real, untampered
  `checkout-egress`/`scanner-egress` policies, and a LIVE, TEMPORARILY
  tampered `scanner-egress` (patched to a non-empty egress list) is rejected
  — proving the check genuinely inspects live policy SHAPE, not just name
  presence — with the original total-deny shape always restored afterwards

Skips automatically if `kind-devsecops-orchestrator` is not reachable —
mirrors `test_kubernetes_client_job_runner_live.py`'s convention.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator

import pytest
from kubernetes import client as k8s_client

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_cluster_capability import (
    KubernetesClientClusterCapability,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"


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
def live_cluster() -> Iterator[None]:
    try:
        load_kubernetes_config(_settings())
        k8s_client.CoreV1Api().list_namespace(_request_timeout=5)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"kind-devsecops-orchestrator cluster not reachable: {exc}")
    yield


def _capability(
    _live_cluster: None, *, cni_enforces_network_policy: bool
) -> KubernetesClientClusterCapability:
    return KubernetesClientClusterCapability(
        k8s_client.StorageV1Api(),
        k8s_client.NetworkingV1Api(),
        k8s_client.CoreV1Api(),
        k8s_client.AuthorizationV1Api(),
        cni_enforces_network_policy=cni_enforces_network_policy,
    )


def test_attestation_off_fails_closed_with_zero_api_calls(
    live_cluster: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even in front of a genuinely-enforcing real cluster, attestation off
    MUST short-circuit BEFORE any API call — proven live by making the real
    `NetworkingV1Api` client explode if it is ever invoked."""
    networking = k8s_client.NetworkingV1Api()

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "list_namespaced_network_policy must not be called when attestation is off"
        )

    monkeypatch.setattr(networking, "list_namespaced_network_policy", _explode)
    capability = KubernetesClientClusterCapability(
        k8s_client.StorageV1Api(),
        networking,
        k8s_client.CoreV1Api(),
        k8s_client.AuthorizationV1Api(),
        cni_enforces_network_policy=False,
    )

    assert capability.network_policies_enforced(_NAMESPACE) is False


def test_real_scan_workspace_storage_class_reports_existence_and_binding_mode(
    live_cluster: None,
) -> None:
    capability = _capability(live_cluster, cni_enforces_network_policy=False)

    info = capability.get_storage_class(_STORAGE_CLASS)

    assert info is not None
    assert info.provisioner == "rancher.io/local-path"
    assert info.volume_binding_mode == "WaitForFirstConsumer"
    assert info.allowed_access_modes == frozenset({"ReadWriteOnce"})


def test_missing_storage_class_returns_none(live_cluster: None) -> None:
    capability = _capability(live_cluster, cni_enforces_network_policy=False)

    assert capability.get_storage_class("definitely-does-not-exist") is None


def test_namespace_workloads_ready_true_for_the_real_security_scans_namespace(
    live_cluster: None,
) -> None:
    """The real `security-scans` namespace, its `checkout`/`scanner`
    ServiceAccounts, and the `scan-job-runner` Role/RoleBindings were applied
    during the PR2 apply batch — the admin kubeconfig identity used by this
    test MUST prove every JobRunner verb is permitted."""
    capability = _capability(live_cluster, cni_enforces_network_policy=False)

    assert capability.namespace_workloads_ready(_NAMESPACE) is True


def test_namespace_workloads_ready_false_for_a_namespace_that_does_not_exist(
    live_cluster: None,
) -> None:
    capability = _capability(live_cluster, cni_enforces_network_policy=False)

    assert capability.namespace_workloads_ready("definitely-does-not-exist") is False


def test_network_policies_enforced_true_against_the_real_untampered_policies(
    live_cluster: None,
) -> None:
    capability = _capability(live_cluster, cni_enforces_network_policy=True)

    assert capability.network_policies_enforced(_NAMESPACE) is True


def _patch_scanner_egress(egress: list[object]) -> None:
    patch_body = json.dumps({"spec": {"egress": egress}})
    subprocess.run(
        [
            "kubectl",
            "-n",
            _NAMESPACE,
            "patch",
            "networkpolicy",
            "scanner-egress",
            "--type=merge",
            "-p",
            patch_body,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_a_live_tampered_scanner_egress_is_rejected(live_cluster: None) -> None:
    """Temporarily patches the REAL `scanner-egress` NetworkPolicy to a
    non-empty (not total-deny) egress rule, proving `network_policies_enforced`
    genuinely inspects live policy SHAPE, not just name presence. Defined
    last in this file (pytest runs a module's tests in definition order) and
    always restores the original total-deny shape in `finally`, so no other
    test/run in this cluster is affected."""
    tampered_egress = [
        {"ports": [{"port": 443, "protocol": "TCP"}], "to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}
    ]
    try:
        _patch_scanner_egress(tampered_egress)
        capability = _capability(live_cluster, cni_enforces_network_policy=True)

        assert capability.network_policies_enforced(_NAMESPACE) is False
    finally:
        _patch_scanner_egress([])
