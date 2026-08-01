"""Render-and-parse proof that `deploy/kubernetes/` actually renders into the
expected resource set with the expected hardening/RBAC/NetworkPolicy shape
(Module 13c PR7). Invokes the real `kustomize build` CLI — skipped if it is
not on `PATH` (no live cluster is ever required; this only renders static
YAML through Kustomize's local, offline builder).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_KUSTOMIZE = shutil.which("kustomize")
pytestmark = pytest.mark.skipif(_KUSTOMIZE is None, reason="kustomize CLI not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[5]
BASE_DIR = REPO_ROOT / "deploy" / "kubernetes" / "base"
OVERLAY_DIR = REPO_ROOT / "deploy" / "kubernetes" / "overlays" / "example"

_JOB_NAMES = {"scan-example-checkout", "scan-example-scanner"}


def _build(target: Path) -> list[dict[str, Any]]:
    assert _KUSTOMIZE is not None
    result = subprocess.run(
        [_KUSTOMIZE, "build", str(target)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return list(yaml.safe_load_all(result.stdout))


def _by_kind(docs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)
    return by_kind


def _jobs(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {job["metadata"]["name"]: job for job in _by_kind(docs)["Job"]}


def _pod_spec(job: dict[str, Any]) -> dict[str, Any]:
    return job["spec"]["template"]["spec"]


def _containers(job: dict[str, Any]) -> list[dict[str, Any]]:
    return _pod_spec(job)["containers"]


def test_base_renders_the_expected_resource_kinds() -> None:
    docs = _build(BASE_DIR)
    by_kind = _by_kind(docs)

    assert len(by_kind.get("Namespace", [])) == 1
    assert len(by_kind.get("ServiceAccount", [])) == 3
    assert len(by_kind.get("Role", [])) == 2
    assert len(by_kind.get("RoleBinding", [])) == 3
    assert len(by_kind.get("NetworkPolicy", [])) == 2
    assert len(by_kind.get("PersistentVolumeClaim", [])) == 1
    assert len(by_kind.get("Job", [])) == 2

    # k8s-backend-enable PR4 (design D-RBAC): exactly ONE justified ClusterRole
    # exception for the orchestrator identity's read-only StorageClass access
    # — never a second one, never for the checkout/scanner workload SAs.
    assert len(by_kind.get("ClusterRole", [])) == 1
    assert len(by_kind.get("ClusterRoleBinding", [])) == 1


def test_roles_grant_no_wildcards_and_only_the_resources_the_lifecycle_touches() -> None:
    docs = _build(BASE_DIR)
    roles = {role["metadata"]["name"]: role for role in _by_kind(docs)["Role"]}

    allowed_resources_by_role = {
        "scan-job-runner": {"jobs", "pods", "pods/log", "persistentvolumeclaims"},
        "scan-orchestrator": {
            "jobs",
            "persistentvolumeclaims",
            "pods",
            "pods/log",
            "serviceaccounts",
            "networkpolicies",
        },
    }
    assert set(roles) == set(allowed_resources_by_role)
    for name, allowed_resources in allowed_resources_by_role.items():
        for rule in roles[name]["rules"]:
            assert "*" not in rule["verbs"]
            assert "*" not in rule.get("apiGroups", [])
            assert "*" not in rule["resources"]
            assert set(rule["resources"]) <= allowed_resources


_ORIGINAL_SCAN_JOB_RUNNER_RULES = [
    {
        "apiGroups": ["batch"],
        "resources": ["jobs"],
        "verbs": ["get", "list", "watch", "create", "delete"],
    },
    {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]},
    {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
    {
        "apiGroups": [""],
        "resources": ["persistentvolumeclaims"],
        "verbs": ["get", "list", "watch", "create", "delete"],
    },
]


def test_scan_job_runner_role_stays_byte_identical_after_the_orchestrator_rbac_addition() -> None:
    """k8s-backend-enable PR4 only adds a comment to `rbac.yaml` and a new,
    additive `orchestrator-rbac.yaml` — `scan-job-runner`'s own rules (the
    workload SAs' least-privilege grant) must never drift as a side effect."""
    docs = _build(BASE_DIR)
    roles = {role["metadata"]["name"]: role for role in _by_kind(docs)["Role"]}

    assert roles["scan-job-runner"]["rules"] == _ORIGINAL_SCAN_JOB_RUNNER_RULES


def test_orchestrator_role_and_binding_scope_the_new_orchestrator_identity_only() -> None:
    docs = _build(BASE_DIR)
    by_kind = _by_kind(docs)

    sa_names = {sa["metadata"]["name"] for sa in by_kind["ServiceAccount"]}
    assert "scan-orchestrator" in sa_names

    role = {role["metadata"]["name"]: role for role in by_kind["Role"]}["scan-orchestrator"]
    verbs_by_resource = {tuple(rule["resources"]): set(rule["verbs"]) for rule in role["rules"]}
    assert verbs_by_resource[("jobs",)] == {"create", "get", "delete", "list"}
    assert verbs_by_resource[("persistentvolumeclaims",)] == {"create", "get", "delete", "list"}
    assert verbs_by_resource[("pods",)] == {"get", "list"}
    assert verbs_by_resource[("pods/log",)] == {"get"}
    assert verbs_by_resource[("serviceaccounts",)] == {"get"}
    assert verbs_by_resource[("networkpolicies",)] == {"list"}

    (binding,) = [
        rb for rb in by_kind["RoleBinding"] if rb["metadata"]["name"] == "scan-orchestrator"
    ]
    assert binding["roleRef"]["name"] == "scan-orchestrator"
    assert [subject["name"] for subject in binding["subjects"]] == ["scan-orchestrator"]


def test_cluster_reader_clusterrole_grants_exactly_two_read_only_rules() -> None:
    """The single justified ClusterRole exception (design D-RBAC): two
    read-only rules — StorageClass (no namespaced equivalent at all) and this
    one namespace's own record (`namespaces` is cluster-scoped, pinned via
    `resourceNames`) — no wildcards, bound to the distinct `scan-orchestrator`
    identity only — never the `checkout`/`scanner` workload SAs."""
    docs = _build(BASE_DIR)
    by_kind = _by_kind(docs)

    (cluster_role,) = by_kind["ClusterRole"]
    assert cluster_role["metadata"]["name"] == "scan-orchestrator-cluster-reader"
    rules_by_resource = {tuple(rule["resources"]): rule for rule in cluster_role["rules"]}

    storage_class_rule = rules_by_resource[("storageclasses",)]
    assert storage_class_rule["apiGroups"] == ["storage.k8s.io"]
    assert set(storage_class_rule["verbs"]) == {"get", "list"}
    assert "resourceNames" not in storage_class_rule

    namespace_rule = rules_by_resource[("namespaces",)]
    assert namespace_rule["apiGroups"] == [""]
    assert set(namespace_rule["verbs"]) == {"get"}
    assert namespace_rule["resourceNames"] == ["security-scans"]

    (cluster_role_binding,) = by_kind["ClusterRoleBinding"]
    assert cluster_role_binding["roleRef"]["name"] == "scan-orchestrator-cluster-reader"
    subject_names = {subject["name"] for subject in cluster_role_binding["subjects"]}
    assert subject_names == {"scan-orchestrator"}
    assert subject_names.isdisjoint({"checkout", "scanner"})


def test_checkout_and_scanner_jobs_use_dedicated_service_accounts() -> None:
    docs = _build(BASE_DIR)
    jobs = _jobs(docs)

    assert _pod_spec(jobs["scan-example-checkout"])["serviceAccountName"] == "checkout"
    assert _pod_spec(jobs["scan-example-scanner"])["serviceAccountName"] == "scanner"


def test_pod_hardening_matches_jobspec_security_defaults() -> None:
    """Mirrors `JobSpec`'s Module 13c PR7 defaults: non-root numeric UID, no
    privilege escalation, dropped capabilities, RuntimeDefault seccomp,
    read-only rootfs, bounded ephemeral-storage."""
    docs = _build(BASE_DIR)
    jobs = _jobs(docs)

    for job in jobs.values():
        pod_spec = _pod_spec(job)
        pod_security = pod_spec["securityContext"]
        assert pod_security["runAsNonRoot"] is True
        assert pod_security["runAsUser"] > 0
        assert pod_security["seccompProfile"]["type"] == "RuntimeDefault"

        (container,) = _containers(job)
        container_security = container["securityContext"]
        assert container_security["allowPrivilegeEscalation"] is False
        assert container_security["capabilities"]["drop"] == ["ALL"]
        assert container_security.get("capabilities", {}).get("add", []) == []
        assert container_security["readOnlyRootFilesystem"] is True

        limits = container["resources"]["limits"]
        assert "ephemeral-storage" in limits
        assert "memory" in limits
        assert "cpu" in limits


def test_job_backoff_and_deadline_match_jobspec_lifecycle_defaults() -> None:
    docs = _build(BASE_DIR)
    for job in _jobs(docs).values():
        assert job["spec"]["backoffLimit"] == 0
        assert job["spec"]["activeDeadlineSeconds"] > 0
        assert job["spec"]["ttlSecondsAfterFinished"] > 0


def test_pvc_uses_read_write_once_and_an_explicit_storage_class() -> None:
    docs = _build(BASE_DIR)
    (pvc,) = _by_kind(docs)["PersistentVolumeClaim"]

    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pvc["spec"]["storageClassName"]


def test_checkout_network_policy_allows_only_dns_and_https_egress() -> None:
    docs = _build(BASE_DIR)
    policies = {p["metadata"]["name"]: p for p in _by_kind(docs)["NetworkPolicy"]}
    checkout_policy = policies["checkout-egress"]

    assert checkout_policy["spec"]["policyTypes"] == ["Egress"]
    ports = {
        (rule_port["protocol"], rule_port["port"])
        for egress_rule in checkout_policy["spec"]["egress"]
        for rule_port in egress_rule.get("ports", [])
    }
    assert ("TCP", 443) in ports
    assert ("UDP", 53) in ports
    assert ("TCP", 53) in ports


def test_scanner_network_policy_denies_all_egress() -> None:
    docs = _build(BASE_DIR)
    policies = {p["metadata"]["name"]: p for p in _by_kind(docs)["NetworkPolicy"]}
    scanner_policy = policies["scanner-egress"]

    assert scanner_policy["spec"]["policyTypes"] == ["Egress"]
    assert scanner_policy["spec"]["egress"] == []


def test_example_overlay_renders_the_same_resource_shape_with_its_own_prefix() -> None:
    base_docs = _build(BASE_DIR)
    overlay_docs = _build(OVERLAY_DIR)

    assert len(overlay_docs) == len(base_docs)

    overlay_jobs = _jobs(overlay_docs)
    assert {name for name in overlay_jobs} == {
        "example-scan-example-checkout",
        "example-scan-example-scanner",
    }
