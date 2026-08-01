"""Live-cluster proof for k8s-backend-enable PR7 (task 7.3) — REAL
`kind-devsecops-orchestrator` API server, no mocks.

`reconcile_orphaned_kubernetes_resources` (Module 13c PR8,
`kubernetes_reconciliation.py`) is pre-existing, unit-tested only against
`FakeKubernetesJobRunner`. This module proves it against a genuinely
orphaned real Job/PVC: a Job is created and left RUNNING (never waited on,
never deleted) — modelling exactly the module's own documented scenario, "a
scan that is NEVER redelivered ... still leaves its Job/PVC behind forever
without a sweep" (e.g. its Celery task process was killed, or its `ScanTask`
was independently marked terminal, so nothing will ever call
`wait_for_job`/`delete_job` for it again). The sweep is proven selective (an
"active" Job/PVC pair whose name IS supplied in `active_names` survives) and
proven to genuinely reach zero cluster residue via `kubectl`, not just the
adapter's own `get_job`/`get_pvc` reads.

Skips automatically if `kind-devsecops-orchestrator` is not reachable —
mirrors `test_kubernetes_client_job_runner_live.py`'s convention.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest
from kubernetes import client as k8s_client

from orchestrator.domain.ports.kubernetes_job_runner_port import JobSpec, PvcSpec
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_job_runner import (
    KubernetesClientJobRunner,
)
from orchestrator.infrastructure.kubernetes.kubernetes_reconciliation import (
    reconcile_orphaned_kubernetes_resources,
)

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"
_RUN_ID = uuid.uuid4().hex[:8]
_BASE_LABELS = {"app.kubernetes.io/name": "security-orchestrator", "test-run": _RUN_ID}


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


@pytest.fixture(scope="module")
def job_runner(live_cluster: None) -> KubernetesClientJobRunner:
    return KubernetesClientJobRunner(k8s_client.BatchV1Api(), k8s_client.CoreV1Api())


def _name(suffix: str) -> str:
    return f"pr7live-{_RUN_ID}-{suffix}"


def _pvc_spec(name: str) -> PvcSpec:
    return PvcSpec(
        name=name, namespace=_NAMESPACE, labels=_BASE_LABELS, storage_class_name=_STORAGE_CLASS
    )


def _long_running_job_spec(name: str, pvc_name: str) -> JobSpec:
    return JobSpec(
        name=name,
        namespace=_NAMESPACE,
        labels={**_BASE_LABELS, "component": "scanner"},
        image="alpine:3.20",
        command=["sh", "-c", "sleep 300"],
        pvc_name=pvc_name,
        pvc_read_only=True,
        allow_network_egress=False,
        timeout_seconds=300,
    )


def _kubectl_get_names(resource: str) -> str:
    result = subprocess.run(
        ["kubectl", "-n", _NAMESPACE, "get", resource, "-l", f"test-run={_RUN_ID}", "-o", "name"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _wait_for_empty(resource: str, *, timeout_seconds: float = 45.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    names = _kubectl_get_names(resource)
    while names and time.monotonic() < deadline:
        time.sleep(2)
        names = _kubectl_get_names(resource)
    return names


def test_sweeps_a_genuinely_orphaned_running_job_and_pvc_while_sparing_the_active_pair(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """Force-kill-mid-flight simulation: create a Job/PVC pair and NEVER call
    `wait_for_job`/`delete_job` on it — exactly what a killed Celery worker
    process (or a `ScanTask` independently marked terminal without the usual
    cleanup running) would leave behind. Confirm it is genuinely RUNNING
    (mid-flight, not yet terminal) via a real `kubectl get pods`, then confirm
    `reconcile_orphaned_kubernetes_resources` against the REAL cluster deletes
    it and reaches zero residue, while an "active" pair (its name supplied in
    `active_names`) survives untouched.
    """
    orphan_pvc = _name("orphan-pvc")
    orphan_job = _name("orphan-scanner")
    active_pvc = _name("active-pvc")
    active_job = _name("active-scanner")

    job_runner.create_pvc(_pvc_spec(orphan_pvc))
    job_runner.create_job(_long_running_job_spec(orphan_job, orphan_pvc))
    job_runner.create_pvc(_pvc_spec(active_pvc))
    job_runner.create_job(_long_running_job_spec(active_job, active_pvc))

    try:
        # Prove "mid-flight": the orphaned Job's Pod is genuinely still
        # running (not completed, not failed) at the moment reconciliation
        # runs — a real interruption, not a Job that already finished.
        deadline = time.monotonic() + 60
        phase = ""
        while time.monotonic() < deadline:
            pods = k8s_client.CoreV1Api().list_namespaced_pod(
                _NAMESPACE, label_selector=f"batch.kubernetes.io/job-name={orphan_job}"
            )
            if pods.items and pods.items[0].status.phase == "Running":
                phase = "Running"
                break
            time.sleep(1)
        assert phase == "Running", "orphaned Job never reached Running before the sweep ran"

        leftover_jobs_before = _kubectl_get_names("jobs")
        leftover_pvcs_before = _kubectl_get_names("pvc")
        assert orphan_job in leftover_jobs_before
        assert orphan_pvc in leftover_pvcs_before

        report = reconcile_orphaned_kubernetes_resources(
            job_runner, namespace=_NAMESPACE, active_names={active_job, active_pvc}
        )

        assert orphan_job in report.deleted_job_names
        assert orphan_pvc in report.deleted_pvc_names
        assert active_job not in report.deleted_job_names
        assert active_pvc not in report.deleted_pvc_names

        # Adapter-level confirmation. `delete_job` uses `propagation_policy=
        # "Background"` (async GC) and the orphaned PVC's own
        # `kubernetes.io/pvc-protection` finalizer only clears once its
        # referencing Pod is actually gone — the API accepts both deletes
        # immediately but the objects linger briefly, so poll rather than
        # asserting the very next instant.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and job_runner.get_pvc(_NAMESPACE, orphan_pvc):
            time.sleep(2)
        assert job_runner.get_job(_NAMESPACE, orphan_job) is False
        assert job_runner.get_pvc(_NAMESPACE, orphan_pvc) is False
        assert job_runner.get_job(_NAMESPACE, active_job) is True
        assert job_runner.get_pvc(_NAMESPACE, active_pvc) is True

        # Real-cluster confirmation, not just the adapter's own reads.
        remaining_jobs = _kubectl_get_names("jobs")
        remaining_pvcs = _kubectl_get_names("pvc")
        assert orphan_job not in remaining_jobs
        assert orphan_pvc not in remaining_pvcs
        assert active_job in remaining_jobs
        assert active_pvc in remaining_pvcs

        # Re-running the sweep with the SAME active_names must be a no-op
        # (idempotent) and must not touch the still-active pair.
        second_report = reconcile_orphaned_kubernetes_resources(
            job_runner, namespace=_NAMESPACE, active_names={active_job, active_pvc}
        )
        assert second_report.deleted_job_names == ()
        assert second_report.deleted_pvc_names == ()
    finally:
        job_runner.delete_job(_NAMESPACE, orphan_job)
        job_runner.delete_pvc(_NAMESPACE, orphan_pvc)
        job_runner.delete_job(_NAMESPACE, active_job)
        job_runner.delete_pvc(_NAMESPACE, active_pvc)


def test_cluster_has_zero_residue_from_this_modules_tests(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """Defined last (pytest runs a module's tests in definition order), after
    the test above's own `finally`-block cleanup: `kubectl`-verified proof
    that this run's unique `test-run` label leaves zero Jobs/Pods/PVCs."""
    leftover_pods = _wait_for_empty("pods")
    leftover_jobs = _wait_for_empty("jobs")
    leftover_pvcs = _wait_for_empty("pvc")

    assert leftover_pods == "", f"leftover pods: {leftover_pods}"
    assert leftover_jobs == "", f"leftover jobs: {leftover_jobs}"
    assert leftover_pvcs == "", f"leftover pvcs: {leftover_pvcs}"
