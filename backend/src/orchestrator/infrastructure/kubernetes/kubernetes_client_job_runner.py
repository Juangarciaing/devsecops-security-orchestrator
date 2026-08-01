"""`KubernetesClientJobRunner` — `kubernetes` Python client implementation of
`KubernetesJobRunnerPort` (k8s-backend-enable PR2b, design D-JobRunner/D-Argv).

This adapter NEVER classifies a Job as a deterministic failure — it only
reports facts (`JobOutcome`) and lets every API/transport exception
(`ApiException`, timeouts) propagate untouched. `KubernetesSplitScanExecution`
is the ONLY place that turns a fact into `KubernetesWorkloadFailedError`
(terminal) or `KubernetesTransientError` (retryable) — see design D-JobRunner
("the adapter never classifies").

`JobSpec`/`PvcSpec` → `V1Job`/`V1PersistentVolumeClaim` mapping (and the three
individually-critical decisions it encodes) lives in `kubernetes_job_mapping`
(PR2a) — this module only owns the CRUD/polling lifecycle against
`BatchV1Api`/`CoreV1Api`.

`propagation_policy="Background"` on `delete_job` is likewise load-bearing,
not a detail: the API's default policy orphans Pods, which keeps the PVC's
`pvc-protection` finalizer alive and the PVC stuck `Terminating` forever.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from kubernetes.client import ApiException  # type: ignore[import-untyped]

from orchestrator.domain.ports.kubernetes_job_runner_port import (
    JobOutcome,
    JobSpec,
    KubernetesJobRunnerPort,
    PvcSpec,
)
from orchestrator.infrastructure.kubernetes.kubernetes_job_mapping import (
    job_outcome_from_status,
    to_v1_job,
    to_v1_pvc,
)

if TYPE_CHECKING:
    from kubernetes.client import BatchV1Api, CoreV1Api

_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409

#: Design D-JobRunner's "Wait strategy" decision: one bounded GET every 2s
#: against a `time.monotonic()` deadline, mirroring `DockerContainerRunner`'s
#: `container.wait(timeout=...)` idiom — one code path, one deadline source,
#: injectable clock/sleep for unit tests (no `watch.Watch()` streaming).
_POLL_INTERVAL_SECONDS = 2.0


def _is_status(exc: ApiException, status: int) -> bool:
    return bool(exc.status == status)


class KubernetesClientJobRunner(KubernetesJobRunnerPort):
    """`kubernetes` Python client adapter over `BatchV1Api`/`CoreV1Api`.

    All I/O is blocking (matches `KubernetesJobRunnerPort`'s framework-free,
    synchronous contract). `now_fn`/`sleep_fn` are injectable purely for unit
    tests — production callers never pass them.
    """

    def __init__(
        self,
        batch_api: BatchV1Api,
        core_api: CoreV1Api,
        *,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
        now_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._batch = batch_api
        self._core = core_api
        self._poll_interval_seconds = poll_interval_seconds
        self._now = now_fn
        self._sleep = sleep_fn

    def get_pvc(self, namespace: str, name: str) -> bool:
        try:
            self._core.read_namespaced_persistent_volume_claim(name, namespace)
        except ApiException as exc:
            if _is_status(exc, _HTTP_NOT_FOUND):
                return False
            raise
        return True

    def create_pvc(self, spec: PvcSpec) -> None:
        try:
            self._core.create_namespaced_persistent_volume_claim(spec.namespace, to_v1_pvc(spec))
        except ApiException as exc:
            if not _is_status(exc, _HTTP_CONFLICT):
                raise

    def get_job(self, namespace: str, name: str) -> bool:
        try:
            self._batch.read_namespaced_job(name, namespace)
        except ApiException as exc:
            if _is_status(exc, _HTTP_NOT_FOUND):
                return False
            raise
        return True

    def create_job(self, spec: JobSpec) -> None:
        try:
            self._batch.create_namespaced_job(spec.namespace, to_v1_job(spec))
        except ApiException as exc:
            if not _is_status(exc, _HTTP_CONFLICT):
                raise

    def wait_for_job(self, namespace: str, name: str, timeout_seconds: int) -> JobOutcome:
        deadline = self._now() + timeout_seconds
        while True:
            status = self._batch.read_namespaced_job_status(name, namespace).status
            outcome = job_outcome_from_status(status)
            if outcome is not None:
                return outcome
            if self._now() >= deadline:
                return JobOutcome(succeeded=False, failed=True, timed_out=True)
            self._sleep(self._poll_interval_seconds)

    def get_job_logs(self, namespace: str, name: str, max_bytes: int) -> str:
        try:
            pods = self._core.list_namespaced_pod(
                namespace, label_selector=f"batch.kubernetes.io/job-name={name}"
            ).items
        except ApiException as exc:
            if _is_status(exc, _HTTP_NOT_FOUND):
                return ""
            raise
        if not pods:
            return ""
        newest = max(pods, key=lambda pod: pod.metadata.creation_timestamp)
        try:
            log: str = self._core.read_namespaced_pod_log(
                newest.metadata.name, namespace, limit_bytes=max_bytes
            )
        except ApiException as exc:
            if _is_status(exc, _HTTP_NOT_FOUND):
                return ""
            raise
        return log[:max_bytes]

    def delete_job(self, namespace: str, name: str) -> None:
        try:
            self._batch.delete_namespaced_job(name, namespace, propagation_policy="Background")
        except ApiException as exc:
            if not _is_status(exc, _HTTP_NOT_FOUND):
                raise

    def delete_pvc(self, namespace: str, name: str) -> None:
        try:
            self._core.delete_namespaced_persistent_volume_claim(name, namespace)
        except ApiException as exc:
            if not _is_status(exc, _HTTP_NOT_FOUND):
                raise

    def list_job_names(self, namespace: str) -> list[str]:
        return [item.metadata.name for item in self._batch.list_namespaced_job(namespace).items]

    def list_pvc_names(self, namespace: str) -> list[str]:
        return [
            item.metadata.name
            for item in self._core.list_namespaced_persistent_volume_claim(namespace).items
        ]
