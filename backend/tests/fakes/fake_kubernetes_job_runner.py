"""`FakeKubernetesJobRunner` — in-memory `KubernetesJobRunnerPort` test double.

Mirrors `FakeContainerRunner`'s conventions: records every call for
call-shape assertions, and lets tests script `wait_for_job` outcomes (one
entry per call, consumed in order) plus one-shot API/transport failures —
all WITHOUT a real Kubernetes API server.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.domain.ports.kubernetes_job_runner_port import (
    JobOutcome,
    JobSpec,
    KubernetesJobRunnerPort,
    PvcSpec,
)

_DEFAULT_OUTCOME = JobOutcome(succeeded=True, failed=False, timed_out=False)


@dataclass(slots=True)
class FakeKubernetesJobRunner(KubernetesJobRunnerPort):
    """In-memory `KubernetesJobRunnerPort`. Script outcomes/errors before calling."""

    pvc_calls: list[PvcSpec] = field(default_factory=list)
    job_calls: list[JobSpec] = field(default_factory=list)
    delete_job_calls: list[tuple[str, str]] = field(default_factory=list)
    delete_pvc_calls: list[tuple[str, str]] = field(default_factory=list)

    _pvcs: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _jobs: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _wait_outcomes: list[JobOutcome] = field(default_factory=list, repr=False)
    _create_job_errors: list[Exception] = field(default_factory=list, repr=False)
    _wait_errors: list[Exception] = field(default_factory=list, repr=False)
    _logs: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def script_wait_outcomes(self, *outcomes: JobOutcome) -> None:
        self._wait_outcomes.extend(outcomes)

    def script_create_job_error(self, error: Exception) -> None:
        """Simulate one Job-submission/API failure, consumed on the next `create_job`."""
        self._create_job_errors.append(error)

    def script_wait_error(self, error: Exception) -> None:
        """Simulate one polling/log-transport failure, consumed on the next `wait_for_job`."""
        self._wait_errors.append(error)

    def script_logs(self, namespace: str, name: str, text: str) -> None:
        self._logs[(namespace, name)] = text

    def seed_existing_pvc(self, namespace: str, name: str) -> None:
        """Pre-populate a PVC as already existing (simulates a crashed prior attempt)."""
        self._pvcs.add((namespace, name))

    def seed_existing_job(self, namespace: str, name: str) -> None:
        """Pre-populate a Job as already existing (simulates a crashed prior attempt)."""
        self._jobs.add((namespace, name))

    def get_pvc(self, namespace: str, name: str) -> bool:
        return (namespace, name) in self._pvcs

    def create_pvc(self, spec: PvcSpec) -> None:
        self.pvc_calls.append(spec)
        self._pvcs.add((spec.namespace, spec.name))

    def get_job(self, namespace: str, name: str) -> bool:
        return (namespace, name) in self._jobs

    def create_job(self, spec: JobSpec) -> None:
        if self._create_job_errors:
            raise self._create_job_errors.pop(0)
        self.job_calls.append(spec)
        self._jobs.add((spec.namespace, spec.name))

    def wait_for_job(self, namespace: str, name: str, timeout_seconds: int) -> JobOutcome:
        if self._wait_errors:
            raise self._wait_errors.pop(0)
        if self._wait_outcomes:
            return self._wait_outcomes.pop(0)
        return _DEFAULT_OUTCOME

    def get_job_logs(self, namespace: str, name: str, max_bytes: int) -> str:
        text = self._logs.get((namespace, name), "")
        return text[:max_bytes]

    def delete_job(self, namespace: str, name: str) -> None:
        self.delete_job_calls.append((namespace, name))
        self._jobs.discard((namespace, name))

    def delete_pvc(self, namespace: str, name: str) -> None:
        self.delete_pvc_calls.append((namespace, name))
        self._pvcs.discard((namespace, name))

    def list_job_names(self, namespace: str) -> list[str]:
        return [ns_name for ns, ns_name in self._jobs if ns == namespace]

    def list_pvc_names(self, namespace: str) -> list[str]:
        return [ns_name for ns, ns_name in self._pvcs if ns == namespace]
