"""Job/PVC mapping between the domain `JobSpec`/`PvcSpec` and the `kubernetes`
client's `V1Job`/`V1PersistentVolumeClaim` (k8s-backend-enable PR2a, design
D-JobRunner/D-Argv).

Three mapping decisions in `to_v1_job` are individually sufficient to
silently destroy this design's isolation guarantees (design D-Argv):

1. `spec.command` maps to `V1Container.args`, NEVER `V1Container.command` —
   setting `command` overrides the image ENTRYPOINT (`git`, `gitleaks`) and
   the Pod fails to exec.
2. `spec.labels` is stamped on BOTH the `V1Job` and the Pod template — the
   NetworkPolicies select Pods, not Jobs; missing the Pod-template copy
   silently gives the scanner Pod unrestricted egress.
3. `serviceAccountName` is derived from `labels["component"]` — `JobSpec`
   carries no dedicated field, so the mapping is the single source of truth,
   fail-closed via `ValueError` when the label is absent or unrecognized.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kubernetes.client import (  # type: ignore[import-untyped]
    V1Capabilities,
    V1Container,
    V1EmptyDirVolumeSource,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSecurityContext,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1SeccompProfile,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)

from orchestrator.domain.ports.kubernetes_job_runner_port import JobOutcome, JobSpec, PvcSpec

if TYPE_CHECKING:
    from kubernetes.client import V1JobStatus

_VALID_COMPONENTS = frozenset({"checkout", "scanner"})

_WORKSPACE_VOLUME_NAME = "workspace"
_TMP_VOLUME_NAME = "tmp"


def to_v1_pvc(spec: PvcSpec) -> V1PersistentVolumeClaim:
    return V1PersistentVolumeClaim(
        metadata=V1ObjectMeta(name=spec.name, namespace=spec.namespace, labels=dict(spec.labels)),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=[spec.access_mode],
            resources=V1ResourceRequirements(requests={"storage": f"{spec.size_gi}Gi"}),
            storage_class_name=spec.storage_class_name,
            volume_mode="Filesystem",
        ),
    )


def to_v1_job(spec: JobSpec) -> V1Job:
    """Map `JobSpec` to a hardened `V1Job` — see module docstring for the
    three individually-critical mapping decisions this function encodes."""
    component = spec.labels.get("component")
    if component not in _VALID_COMPONENTS:
        raise ValueError(
            f"JobSpec.labels['component'] must be one of {sorted(_VALID_COMPONENTS)}, "
            f"got {component!r}"
        )
    if spec.allow_network_egress != (component == "checkout"):
        raise ValueError(
            "JobSpec.allow_network_egress disagrees with labels['component']: egress is "
            "enforced by the NetworkPolicy the component label selects, not by this flag "
            f"(component={component!r}, allow_network_egress={spec.allow_network_egress!r})"
        )

    resource_quantities = {
        "memory": f"{spec.memory_mb}Mi",
        "cpu": f"{spec.cpu_millis}m",
        "ephemeral-storage": f"{spec.ephemeral_storage_mb}Mi",
    }
    container = V1Container(
        name=component,
        image=spec.image,
        args=list(spec.command),
        env=[V1EnvVar(name=key, value=value) for key, value in spec.env.items()],
        volume_mounts=[
            V1VolumeMount(
                name=_WORKSPACE_VOLUME_NAME,
                mount_path="/workspace",
                read_only=spec.pvc_read_only,
            ),
            V1VolumeMount(name=_TMP_VOLUME_NAME, mount_path="/tmp"),
        ],
        resources=V1ResourceRequirements(requests=resource_quantities, limits=resource_quantities),
        security_context=V1SecurityContext(
            run_as_non_root=spec.run_as_non_root,
            run_as_user=spec.run_as_user,
            allow_privilege_escalation=spec.allow_privilege_escalation,
            capabilities=V1Capabilities(drop=list(spec.capabilities_drop)),
            seccomp_profile=V1SeccompProfile(type=spec.seccomp_profile_type),
            read_only_root_filesystem=spec.read_only_root_filesystem,
        ),
    )
    pod_spec = V1PodSpec(
        containers=[container],
        restart_policy="Never",
        service_account_name=component,
        automount_service_account_token=False,
        volumes=[
            V1Volume(
                name=_WORKSPACE_VOLUME_NAME,
                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                    claim_name=spec.pvc_name, read_only=spec.pvc_read_only
                ),
            ),
            V1Volume(name=_TMP_VOLUME_NAME, empty_dir=V1EmptyDirVolumeSource()),
        ],
        security_context=V1PodSecurityContext(
            run_as_non_root=spec.run_as_non_root,
            run_as_user=spec.run_as_user,
        ),
    )
    job_spec = V1JobSpec(
        template=V1PodTemplateSpec(
            metadata=V1ObjectMeta(labels=dict(spec.labels)),
            spec=pod_spec,
        ),
        backoff_limit=spec.backoff_limit,
        active_deadline_seconds=spec.active_deadline_seconds,
        ttl_seconds_after_finished=spec.ttl_seconds_after_finished,
    )
    return V1Job(
        metadata=V1ObjectMeta(name=spec.name, namespace=spec.namespace, labels=dict(spec.labels)),
        spec=job_spec,
    )


def job_outcome_from_status(status: V1JobStatus) -> JobOutcome | None:
    """`None` means "not yet terminal — keep polling". Terminal when
    `status.succeeded >= 1`, `status.failed >= 1`, or a `Complete`/`Failed`
    condition is `True` (design D-JobRunner)."""
    conditions = status.conditions or []
    failed_condition = next(
        (c for c in conditions if c.type == "Failed" and c.status == "True"), None
    )
    complete_condition = next(
        (c for c in conditions if c.type == "Complete" and c.status == "True"), None
    )
    if (status.succeeded or 0) >= 1 or complete_condition is not None:
        return JobOutcome(succeeded=True, failed=False, timed_out=False)
    if (status.failed or 0) >= 1 or failed_condition is not None:
        timed_out = failed_condition is not None and failed_condition.reason == "DeadlineExceeded"
        return JobOutcome(succeeded=False, failed=True, timed_out=timed_out)
    return None
