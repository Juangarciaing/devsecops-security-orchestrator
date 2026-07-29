"""RED->GREEN tests for the orphaned-Job/PVC reconciliation sweep (Module
13c PR8, spec's "Deterministic PVC Lifecycle and Observability" —
"reconciliation MUST remove orphans"). Proven entirely against
`FakeKubernetesJobRunner`; idempotent by construction since `delete_job`/
`delete_pvc` are no-ops on an already-absent resource (PR6).
"""

from __future__ import annotations

from orchestrator.domain.ports.kubernetes_job_runner_port import JobSpec, PvcSpec
from orchestrator.infrastructure.kubernetes.kubernetes_reconciliation import (
    reconcile_orphaned_kubernetes_resources,
)
from tests.fakes.fake_kubernetes_job_runner import FakeKubernetesJobRunner

_NAMESPACE = "security-scans"


def _job_spec(name: str) -> JobSpec:
    return JobSpec(
        name=name,
        namespace=_NAMESPACE,
        labels={},
        image="alpine/git:2.54.0",
        command=["clone"],
        pvc_name="scan-pvc",
        pvc_read_only=False,
        allow_network_egress=True,
    )


def test_deletes_only_resources_absent_from_active_names() -> None:
    """A worker that died mid-scan leaves `orphan-*` behind while
    `active-*` is a genuinely still-running scan (Celery, not this
    routine, remains the retry authority — reconciliation only deletes)."""
    runner = FakeKubernetesJobRunner()
    runner.create_job(_job_spec("orphan-checkout"))
    runner.create_job(_job_spec("active-checkout"))
    runner.create_pvc(PvcSpec(name="orphan-pvc", namespace=_NAMESPACE, labels={}))
    runner.create_pvc(PvcSpec(name="active-pvc", namespace=_NAMESPACE, labels={}))

    report = reconcile_orphaned_kubernetes_resources(
        runner, namespace=_NAMESPACE, active_names={"active-checkout", "active-pvc"}
    )

    assert sorted(report.deleted_job_names) == ["orphan-checkout"]
    assert sorted(report.deleted_pvc_names) == ["orphan-pvc"]
    assert runner.get_job(_NAMESPACE, "active-checkout") is True
    assert runner.get_pvc(_NAMESPACE, "active-pvc") is True
    assert runner.get_job(_NAMESPACE, "orphan-checkout") is False
    assert runner.get_pvc(_NAMESPACE, "orphan-pvc") is False


def test_is_a_noop_when_nothing_is_orphaned() -> None:
    runner = FakeKubernetesJobRunner()
    runner.create_job(_job_spec("active-checkout"))

    report = reconcile_orphaned_kubernetes_resources(
        runner, namespace=_NAMESPACE, active_names={"active-checkout"}
    )

    assert report.deleted_job_names == ()
    assert report.deleted_pvc_names == ()
    assert runner.get_job(_NAMESPACE, "active-checkout") is True


def test_is_idempotent_on_repeated_runs() -> None:
    runner = FakeKubernetesJobRunner()
    runner.create_job(_job_spec("orphan-checkout"))

    first = reconcile_orphaned_kubernetes_resources(
        runner, namespace=_NAMESPACE, active_names=set()
    )
    second = reconcile_orphaned_kubernetes_resources(
        runner, namespace=_NAMESPACE, active_names=set()
    )

    assert first.deleted_job_names == ("orphan-checkout",)
    assert second.deleted_job_names == ()
