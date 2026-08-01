"""`kubernetes_job_mapping` — pure `JobSpec`/`PvcSpec` → `V1Job`/
`V1PersistentVolumeClaim` mapping tests (k8s-backend-enable PR2a, tasks
2.1-2.6).

No `kubernetes` API client involved — these functions are pure. CRUD/polling
proof against a mocked `BatchV1Api`/`CoreV1Api` lives in
`test_kubernetes_client_job_runner.py` (PR2b); live-cluster proof lives in
`tests/integration/test_kubernetes_client_job_runner_live.py` (PR2c).
"""

from __future__ import annotations

import pytest

from orchestrator.domain.ports.kubernetes_job_runner_port import JobSpec, PvcSpec
from orchestrator.infrastructure.kubernetes.kubernetes_job_mapping import to_v1_job, to_v1_pvc

_NAMESPACE = "security-scans"


def _checkout_job_spec(**overrides: object) -> JobSpec:
    defaults: dict[str, object] = {
        "name": "scan-abc-checkout",
        "namespace": _NAMESPACE,
        "labels": {"app.kubernetes.io/name": "security-orchestrator", "component": "checkout"},
        "image": "alpine/git:v2.45.2",
        "command": ["clone", "--depth", "1", "https://example.com/repo.git", "/workspace/checkout"],
        "pvc_name": "scan-abc-pvc",
        "pvc_read_only": False,
        "allow_network_egress": True,
    }
    defaults.update(overrides)
    return JobSpec(**defaults)  # type: ignore[arg-type]


def _scanner_job_spec(**overrides: object) -> JobSpec:
    defaults: dict[str, object] = {
        "name": "scan-abc-scanner",
        "namespace": _NAMESPACE,
        "labels": {"app.kubernetes.io/name": "security-orchestrator", "component": "scanner"},
        "image": "ghcr.io/gitleaks/gitleaks:v8.30.1",
        "command": ["dir", "/workspace/checkout", "--exit-code=2"],
        "pvc_name": "scan-abc-pvc",
        "pvc_read_only": True,
        "allow_network_egress": False,
    }
    defaults.update(overrides)
    return JobSpec(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2.1 args-not-command
# ---------------------------------------------------------------------------


def test_to_v1_job_maps_command_to_args_never_command() -> None:
    v1_job = to_v1_job(_checkout_job_spec())

    container = v1_job.spec.template.spec.containers[0]
    assert container.command is None
    assert container.args == [
        "clone",
        "--depth",
        "1",
        "https://example.com/repo.git",
        "/workspace/checkout",
    ]


# ---------------------------------------------------------------------------
# 2.2 Pod-template labels
# ---------------------------------------------------------------------------


def test_to_v1_job_stamps_pod_template_labels_from_job_spec_labels() -> None:
    spec = _scanner_job_spec()

    v1_job = to_v1_job(spec)

    assert v1_job.metadata.labels == spec.labels
    assert v1_job.spec.template.metadata.labels == spec.labels


# ---------------------------------------------------------------------------
# 2.3 SA derivation
# ---------------------------------------------------------------------------


def test_to_v1_job_derives_service_account_from_component_label() -> None:
    checkout_job = to_v1_job(_checkout_job_spec())
    scanner_job = to_v1_job(_scanner_job_spec())

    assert checkout_job.spec.template.spec.service_account_name == "checkout"
    assert scanner_job.spec.template.spec.service_account_name == "scanner"


def test_to_v1_job_raises_on_missing_component_label() -> None:
    spec = _checkout_job_spec(labels={"app.kubernetes.io/name": "security-orchestrator"})

    with pytest.raises(ValueError, match="component"):
        to_v1_job(spec)


def test_to_v1_job_raises_on_unknown_component_label() -> None:
    spec = _checkout_job_spec(labels={"component": "rev-parse-typo"})

    with pytest.raises(ValueError, match="component"):
        to_v1_job(spec)


# ---------------------------------------------------------------------------
# 2.4 egress cross-check
# ---------------------------------------------------------------------------


def test_to_v1_job_raises_when_egress_flag_disagrees_with_checkout_component() -> None:
    spec = _checkout_job_spec(allow_network_egress=False)

    with pytest.raises(ValueError, match="allow_network_egress"):
        to_v1_job(spec)


def test_to_v1_job_raises_when_egress_flag_disagrees_with_scanner_component() -> None:
    spec = _scanner_job_spec(allow_network_egress=True)

    with pytest.raises(ValueError, match="allow_network_egress"):
        to_v1_job(spec)


# ---------------------------------------------------------------------------
# 2.5 hardening block
# ---------------------------------------------------------------------------


def test_to_v1_job_applies_full_hardening_block() -> None:
    v1_job = to_v1_job(_scanner_job_spec())

    pod_spec = v1_job.spec.template.spec
    container = pod_spec.containers[0]
    security_context = container.security_context

    assert security_context.run_as_non_root is True
    assert security_context.run_as_user == 65532
    assert security_context.allow_privilege_escalation is False
    assert security_context.capabilities.drop == ["ALL"]
    assert security_context.seccomp_profile.type == "RuntimeDefault"
    assert security_context.read_only_root_filesystem is True
    assert pod_spec.restart_policy == "Never"
    assert pod_spec.automount_service_account_token is False
    assert v1_job.spec.backoff_limit == 0
    assert v1_job.spec.active_deadline_seconds == 150  # timeout_seconds(120) + 30
    assert v1_job.spec.ttl_seconds_after_finished == 300

    resources = container.resources
    assert resources.requests == {"memory": "512Mi", "cpu": "1000m", "ephemeral-storage": "256Mi"}
    assert resources.limits == {"memory": "512Mi", "cpu": "1000m", "ephemeral-storage": "256Mi"}

    tmp_mount = next(m for m in container.volume_mounts if m.mount_path == "/tmp")
    tmp_volume = next(v for v in pod_spec.volumes if v.name == tmp_mount.name)
    assert tmp_volume.empty_dir is not None


def test_to_v1_job_mounts_pvc_at_workspace_with_read_only_matching_spec() -> None:
    v1_job = to_v1_job(_scanner_job_spec(pvc_read_only=True))

    pod_spec = v1_job.spec.template.spec
    workspace_mount = next(
        m for m in pod_spec.containers[0].volume_mounts if m.mount_path == "/workspace"
    )
    assert workspace_mount.read_only is True
    workspace_volume = next(v for v in pod_spec.volumes if v.name == workspace_mount.name)
    assert workspace_volume.persistent_volume_claim.claim_name == "scan-abc-pvc"
    assert workspace_volume.persistent_volume_claim.read_only is True


def test_to_v1_pvc_maps_size_and_access_mode() -> None:
    v1_pvc = to_v1_pvc(
        PvcSpec(name="scan-abc-pvc", namespace=_NAMESPACE, labels={"a": "b"}, size_gi=2)
    )

    assert v1_pvc.metadata.name == "scan-abc-pvc"
    assert v1_pvc.spec.access_modes == ["ReadWriteOnce"]
    assert v1_pvc.spec.resources.requests == {"storage": "2Gi"}
