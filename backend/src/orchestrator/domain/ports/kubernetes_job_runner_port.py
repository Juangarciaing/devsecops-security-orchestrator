"""`KubernetesJobRunnerPort` — contract for the split checkout/scanner Job
lifecycle against a Kubernetes-like API (Module 13c PR6).

Framework-free: this module MUST NOT import the `kubernetes` client SDK —
only a concrete adapter would do that (none exists yet; this slice proves
the lifecycle against `tests/fakes/fake_kubernetes_job_runner.py` only, per
the spec's "Verification and Non-Requirements" — no live cluster wiring, no
Kustomize/RBAC rendering, and no `process_scan_task` selection is in scope
here). Mirrors `ContainerRunnerPort`'s framework-free-port pattern.

All methods are synchronous (Job orchestration is blocking API/polling I/O,
same rationale as `ContainerRunnerPort`). `create_pvc`/`create_job` MUST be
called ONLY after the matching `get_pvc`/`get_job` reports absence —
duplicate-delivery safety (spec's "Deterministic PVC Lifecycle") is the
CALLER's responsibility, not this port's. `delete_job`/`delete_pvc` MUST be
a no-op (never raise) when the resource is already absent (NotFound cleanup).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PvcSpec:
    """One bounded, per-scan ephemeral `PersistentVolumeClaim`.

    `WaitForFirstConsumer` binding (spec: "Split Public-Repository PVC
    Workspace") defers provisioning until the checkout Job's Pod is
    scheduled, so the PVC never binds to a zone/node the scanner Pod cannot
    also reach.
    """

    name: str
    namespace: str
    labels: dict[str, str]
    size_gi: int = 1
    access_mode: str = "ReadWriteOnce"
    volume_binding_mode: str = "WaitForFirstConsumer"
    #: MUST match a StorageClass proven by `kubernetes_preflight` (Module
    #: 13c PR7) to support `access_mode`/`volume_binding_mode` above — `None`
    #: lets the cluster's default StorageClass apply, but a Kubernetes
    #: deployment is only ever considered available once THAT StorageClass
    #: (default or named) has passed the fail-closed preflight.
    storage_class_name: str | None = None


@dataclass(frozen=True, slots=True)
class JobSpec:
    """One checkout OR scanner `Job` — never both roles at once.

    `env` MUST be empty for the scanner Job (spec: "the scanner MUST receive
    neither credentials nor network egress") — the caller is responsible for
    never populating it there. Conservative resource/PID defaults only;
    real tuning is out of scope for this slice.

    The fields below (Module 13c PR7) are the Pod-level `SecurityContext`
    shape PR6's verify report flagged as missing: non-root numeric UID, no
    privilege escalation, dropped Linux capabilities, `RuntimeDefault`
    seccomp, a read-only root filesystem, and a bounded ephemeral-storage
    ceiling alongside the existing memory/CPU/PID limits. `deploy/kubernetes/
    base/*.yaml` renders the equivalent static shape for the rendered
    manifests (Kustomize YAML is not templated from these values at build
    time); a future concrete Kubernetes API adapter (PR8+) is what would
    actually read these fields to construct the real `V1PodSecurityContext`.
    """

    name: str
    namespace: str
    labels: dict[str, str]
    image: str
    command: list[str]
    pvc_name: str
    pvc_read_only: bool
    allow_network_egress: bool
    env: dict[str, str] = field(default_factory=dict)
    memory_mb: int = 512
    cpu_millis: int = 1000
    pids_limit: int = 128
    ephemeral_storage_mb: int = 256
    timeout_seconds: int = 120
    backoff_limit: int = 0
    ttl_seconds_after_finished: int = 300
    run_as_non_root: bool = True
    run_as_user: int = 65532
    allow_privilege_escalation: bool = False
    capabilities_drop: tuple[str, ...] = ("ALL",)
    seccomp_profile_type: str = "RuntimeDefault"
    read_only_root_filesystem: bool = True

    @property
    def active_deadline_seconds(self) -> int:
        """`timeout_seconds` plus a fixed 30s margin (spec: "deadline+30")."""
        return self.timeout_seconds + 30


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Terminal (or timed-out) state of one polled `Job`."""

    succeeded: bool
    failed: bool
    timed_out: bool


class KubernetesJobRunnerPort(ABC):
    """Contract for the primitives one split checkout/scanner Job lifecycle needs."""

    @abstractmethod
    def get_pvc(self, namespace: str, name: str) -> bool:
        """Whether a PVC named `name` already exists in `namespace`."""

    @abstractmethod
    def create_pvc(self, spec: PvcSpec) -> None:
        """Create the PVC described by `spec`. Callers MUST call `get_pvc` first."""

    @abstractmethod
    def get_job(self, namespace: str, name: str) -> bool:
        """Whether a Job named `name` already exists in `namespace`."""

    @abstractmethod
    def create_job(self, spec: JobSpec) -> None:
        """Submit the Job described by `spec`. Callers MUST call `get_job` first."""

    @abstractmethod
    def wait_for_job(self, namespace: str, name: str, timeout_seconds: int) -> JobOutcome:
        """Block until Job `name` reaches a terminal state or `timeout_seconds` elapses."""

    @abstractmethod
    def get_job_logs(self, namespace: str, name: str, max_bytes: int) -> str:
        """Return up to `max_bytes` of the Job's Pod logs, truncated if longer."""

    @abstractmethod
    def delete_job(self, namespace: str, name: str) -> None:
        """Delete Job `name` and its Pods. MUST be a no-op if already absent."""

    @abstractmethod
    def delete_pvc(self, namespace: str, name: str) -> None:
        """Delete PVC `name`. MUST be a no-op if already absent."""

    @abstractmethod
    def list_job_names(self, namespace: str) -> list[str]:
        """Names of every Job that currently exists in `namespace` (Module 13c
        PR8 — reconciliation's discovery step; never used by the split-scan
        lifecycle itself, which always addresses Jobs by exact name)."""

    @abstractmethod
    def list_pvc_names(self, namespace: str) -> list[str]:
        """Names of every PVC that currently exists in `namespace` (Module
        13c PR8 — reconciliation's discovery step)."""
