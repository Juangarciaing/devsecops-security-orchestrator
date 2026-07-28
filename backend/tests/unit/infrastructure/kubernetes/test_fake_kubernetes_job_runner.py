"""`FakeKubernetesJobRunner` — the in-memory `KubernetesJobRunnerPort` test
double `KubernetesSplitScanExecution` unit tests script against (no
Kubernetes API server needed)."""

from __future__ import annotations

from orchestrator.domain.ports.kubernetes_job_runner_port import JobOutcome, JobSpec, PvcSpec
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


def test_get_reports_absent_until_create_then_present() -> None:
    fake = FakeKubernetesJobRunner()

    assert fake.get_pvc(_NAMESPACE, "scan-pvc") is False
    fake.create_pvc(PvcSpec(name="scan-pvc", namespace=_NAMESPACE, labels={}))
    assert fake.get_pvc(_NAMESPACE, "scan-pvc") is True

    assert fake.get_job(_NAMESPACE, "scan-checkout") is False
    fake.create_job(_job_spec("scan-checkout"))
    assert fake.get_job(_NAMESPACE, "scan-checkout") is True


def test_delete_is_a_no_op_when_already_absent() -> None:
    fake = FakeKubernetesJobRunner()

    fake.delete_job(_NAMESPACE, "never-created")
    fake.delete_pvc(_NAMESPACE, "never-created")

    assert fake.delete_job_calls == [(_NAMESPACE, "never-created")]
    assert fake.delete_pvc_calls == [(_NAMESPACE, "never-created")]


def test_wait_outcomes_are_consumed_in_scripted_order_then_default_success() -> None:
    fake = FakeKubernetesJobRunner()
    first = JobOutcome(succeeded=False, failed=True, timed_out=False)
    fake.script_wait_outcomes(first)

    assert fake.wait_for_job(_NAMESPACE, "job-1", 60) is first
    default = fake.wait_for_job(_NAMESPACE, "job-2", 60)
    assert default.succeeded is True


def test_scripted_errors_raise_once_then_clear() -> None:
    fake = FakeKubernetesJobRunner()
    fake.script_create_job_error(RuntimeError("boom"))

    try:
        fake.create_job(_job_spec("scan-checkout"))
        raised = False
    except RuntimeError:
        raised = True
    assert raised is True

    fake.create_job(_job_spec("scan-checkout"))
    assert fake.get_job(_NAMESPACE, "scan-checkout") is True


def test_logs_are_truncated_to_max_bytes() -> None:
    fake = FakeKubernetesJobRunner()
    fake.script_logs(_NAMESPACE, "scan-checkout", "0123456789")

    assert fake.get_job_logs(_NAMESPACE, "scan-checkout", 4) == "0123"
    assert fake.get_job_logs(_NAMESPACE, "missing", 4) == ""
