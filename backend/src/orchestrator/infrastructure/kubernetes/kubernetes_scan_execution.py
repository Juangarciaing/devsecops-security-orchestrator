"""`KubernetesSplitScanExecution` — the two-Job split-workload lifecycle
(Module 13c PR6): one bounded, per-scan ephemeral PVC shared by a checkout
Job (owns clone credentials, may reach Git+DNS only) and a scanner Job
(zero credentials, zero network egress).

DISABLED/DORMANT BY DEFAULT: Docker remains the sole active execution path
(spec's "Explicit Backend Selection and Compatibility") — nothing in this
module is wired into `workers/tasks/process_scan.py`'s live routing, no
settings/feature-flag selects it, and no real `kubernetes` client talks to
an actual cluster. This slice proves the lifecycle in isolation against
`KubernetesJobRunnerPort`'s fake test double
(`tests/fakes/fake_kubernetes_job_runner.py`) only. Kustomize/RBAC
rendering and NetworkPolicy/StorageClass preflight enforcement are PR7;
backend selection, telemetry, and optional kind/k3d proof are PR8.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.domain.ports.kubernetes_job_runner_port import JobSpec, PvcSpec

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_job_runner_port import KubernetesJobRunnerPort
    from orchestrator.domain.value_objects.enums import ScannerType

#: Bounded, redacted log cap (spec: "bounded, redacted logs ... without
#: labels, annotations, or secrets" — no unbounded payload transport).
_MAX_LOG_BYTES = 65_536

#: Truncating `scan_task_id.hex` (32 chars) keeps every derived name well
#: under Kubernetes' 63-char RFC 1123 label limit, including the longest
#: suffix ("-checkout").
_NAME_HEX_LEN = 20


class KubernetesPrivateRepositoryError(Exception):
    """Deterministic, credential-free failure: the repository requires
    authentication, which this backend does not support. Raised BEFORE any
    PVC/Job is created (spec's "Split Public-Repository PVC Workspace" —
    "Private repository" scenario)."""


class KubernetesWorkloadFailedError(Exception):
    """Deterministic checkout or scanner Job failure (repository/scanner
    failure, or the Job's own `activeDeadlineSeconds` elapsing) — terminal,
    never retried (spec's "Bounded Result Transport and Failure
    Semantics")."""


class KubernetesTransientError(Exception):
    """Job submission, API, polling, or log-transport failure — MAY be
    retried by Celery alone; this backend never retries or falls back to
    Docker mid-scan (spec's "Bounded Result Transport and Failure
    Semantics")."""


@dataclass(frozen=True, slots=True)
class KubernetesScanResult:
    """Bounded, redacted logs collected from one successful split-workload run."""

    checkout_log: str
    scanner_log: str


def _bounded_name(scan_task_id: uuid.UUID, suffix: str) -> str:
    return f"scan-{scan_task_id.hex[:_NAME_HEX_LEN]}-{suffix}"


class KubernetesSplitScanExecution:
    """Orchestrates one checkout Job + one scanner Job sharing one PVC.

    Idempotent by construction: `_ensure_pvc`/`_run_job` always call the
    matching `get_pvc`/`get_job` before creating anything, so a Celery
    redelivery after a worker crash discovers and reuses whatever the prior
    attempt already created instead of duplicating it (spec's "Deterministic
    PVC Lifecycle and Observability").
    """

    def __init__(
        self,
        runner: KubernetesJobRunnerPort,
        *,
        namespace: str,
        checkout_image: str,
        scanner_image: str,
        scanner_command: list[str],
        timeout_seconds: int = 120,
    ) -> None:
        self._runner = runner
        self._namespace = namespace
        self._checkout_image = checkout_image
        self._scanner_image = scanner_image
        self._scanner_command = scanner_command
        self._timeout_seconds = timeout_seconds

    def execute(
        self,
        *,
        clone_url: str,
        ref: str,
        credential_ref: str | None,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
    ) -> KubernetesScanResult:
        """Run the split checkout/scanner lifecycle for one `ScanTask`.

        Raises `KubernetesPrivateRepositoryError` (credential-free,
        before any workload) if `credential_ref` is set;
        `KubernetesWorkloadFailedError` (terminal) if either Job fails or
        times out; `KubernetesTransientError` (Celery-retryable) on any
        submission/API/polling/log-transport failure. Jobs and the PVC are
        ALWAYS deleted before returning or raising — success, failure,
        timeout, or cancellation never leaves an orphan (spec's
        "Deterministic PVC Lifecycle and Observability").
        """
        if credential_ref is not None:
            raise KubernetesPrivateRepositoryError(
                "credential resolution not supported by the Kubernetes backend"
            )

        pvc_name = _bounded_name(scan_task_id, "pvc")
        checkout_name = _bounded_name(scan_task_id, "checkout")
        scanner_name = _bounded_name(scan_task_id, "scanner")
        labels = {
            "app.kubernetes.io/name": "security-orchestrator",
            "scan-task-id": str(scan_task_id),
            "scanner-type": scanner_type.value,
        }

        try:
            self._ensure_pvc(pvc_name, labels)

            checkout_log = self._run_job(
                JobSpec(
                    name=checkout_name,
                    namespace=self._namespace,
                    labels={**labels, "component": "checkout"},
                    image=self._checkout_image,
                    command=[
                        "clone",
                        "--depth",
                        "1",
                        "--single-branch",
                        "--branch",
                        ref,
                        clone_url,
                        "/workspace/checkout",
                    ],
                    pvc_name=pvc_name,
                    pvc_read_only=False,
                    allow_network_egress=True,
                    timeout_seconds=self._timeout_seconds,
                ),
                role="checkout",
            )

            scanner_log = self._run_job(
                JobSpec(
                    name=scanner_name,
                    namespace=self._namespace,
                    labels={**labels, "component": "scanner"},
                    image=self._scanner_image,
                    command=self._scanner_command,
                    pvc_name=pvc_name,
                    pvc_read_only=True,
                    allow_network_egress=False,
                    timeout_seconds=self._timeout_seconds,
                ),
                role="scanner",
            )
        finally:
            self._cleanup(checkout_name, scanner_name, pvc_name)

        return KubernetesScanResult(checkout_log=checkout_log, scanner_log=scanner_log)

    def _ensure_pvc(self, name: str, labels: dict[str, str]) -> None:
        if self._runner.get_pvc(self._namespace, name):
            return
        self._runner.create_pvc(PvcSpec(name=name, namespace=self._namespace, labels=labels))

    def _run_job(self, spec: JobSpec, *, role: str) -> str:
        """Submit-or-discover `spec`, wait for it, and return its bounded log.

        Any exception raised BY the runner (submission/API/polling/log
        transport) is reclassified as `KubernetesTransientError`. A Job that
        completes but did not succeed — including hitting its own
        `activeDeadlineSeconds` — is a deterministic outcome of THIS run and
        is therefore terminal (`KubernetesWorkloadFailedError`), matching
        the Docker backend's precedent for a timed-out container.
        """
        try:
            if not self._runner.get_job(spec.namespace, spec.name):
                self._runner.create_job(spec)
            outcome = self._runner.wait_for_job(spec.namespace, spec.name, spec.timeout_seconds)
            log = self._runner.get_job_logs(spec.namespace, spec.name, _MAX_LOG_BYTES)
        except Exception as exc:
            raise KubernetesTransientError(
                f"{role} Job submission/polling/log-transport failed: {exc}"
            ) from exc

        if outcome.timed_out or outcome.failed or not outcome.succeeded:
            raise KubernetesWorkloadFailedError(f"{role} Job did not complete successfully")
        return log

    def _cleanup(self, checkout_name: str, scanner_name: str, pvc_name: str) -> None:
        self._runner.delete_job(self._namespace, checkout_name)
        self._runner.delete_job(self._namespace, scanner_name)
        self._runner.delete_pvc(self._namespace, pvc_name)
