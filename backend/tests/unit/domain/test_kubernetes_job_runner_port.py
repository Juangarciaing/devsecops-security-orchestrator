"""`JobSpec`/`PvcSpec` MUST carry Pod-level SecurityContext hardening shape
fields (Module 13c PR7) — PR6's verify report flagged their absence as a
WARNING: without these fields, nothing in the dataclasses can express
non-root/numeric UID, no-privilege-escalation, dropped capabilities,
RuntimeDefault seccomp, read-only root filesystem, or a bounded
ephemeral-storage ceiling. This slice closes that gap in code (the fields
below); `deploy/kubernetes/base/*.yaml` renders the equivalent static shape
(proven separately by `test_kubernetes_manifests_render.py`), since Kustomize
YAML is not templated from these Python values at build time.
"""

from __future__ import annotations

from orchestrator.domain.ports.kubernetes_job_runner_port import JobSpec, PvcSpec

_COMMON_JOB_KWARGS = {
    "name": "scan-deadbeefdeadbeefdead-checkout",
    "namespace": "security-scans",
    "labels": {"app.kubernetes.io/name": "security-orchestrator"},
    "image": "alpine/git:2.54.0@sha256:deadbeef",
    "command": ["clone"],
    "pvc_name": "scan-deadbeefdeadbeefdead-pvc",
    "pvc_read_only": False,
    "allow_network_egress": True,
}


def test_job_spec_defaults_to_a_hardened_non_root_pod_security_context() -> None:
    spec = JobSpec(**_COMMON_JOB_KWARGS)

    assert spec.run_as_non_root is True
    assert isinstance(spec.run_as_user, int)
    assert spec.run_as_user > 0  # numeric, non-root (never UID 0)
    assert spec.allow_privilege_escalation is False
    assert spec.capabilities_drop == ("ALL",)
    assert spec.seccomp_profile_type == "RuntimeDefault"
    assert spec.read_only_root_filesystem is True


def test_job_spec_bounds_ephemeral_storage_alongside_memory_cpu_and_pids() -> None:
    spec = JobSpec(**_COMMON_JOB_KWARGS)

    assert spec.ephemeral_storage_mb > 0
    assert spec.memory_mb > 0
    assert spec.cpu_millis > 0
    assert spec.pids_limit > 0


def test_job_spec_hardening_fields_are_overridable_per_call() -> None:
    spec = JobSpec(
        **_COMMON_JOB_KWARGS,
        run_as_user=10001,
        ephemeral_storage_mb=1024,
    )

    assert spec.run_as_user == 10001
    assert spec.ephemeral_storage_mb == 1024


def test_pvc_spec_carries_an_explicit_storage_class_name() -> None:
    spec = PvcSpec(
        name="scan-deadbeefdeadbeefdead-pvc",
        namespace="security-scans",
        labels={"app.kubernetes.io/name": "security-orchestrator"},
        storage_class_name="scan-workspace",
    )

    assert spec.storage_class_name == "scan-workspace"


def test_pvc_spec_storage_class_name_defaults_to_none() -> None:
    spec = PvcSpec(
        name="scan-deadbeefdeadbeefdead-pvc",
        namespace="security-scans",
        labels={},
    )

    assert spec.storage_class_name is None
