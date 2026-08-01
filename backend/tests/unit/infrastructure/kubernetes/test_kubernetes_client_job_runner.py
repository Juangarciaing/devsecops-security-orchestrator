"""`KubernetesClientJobRunner` — mocked-API-client unit tests (k8s-backend-enable
PR2b, tasks 2.7-2.13).

Mirrors `test_docker_container_runner.py`'s convention: these tests only prove
the `kubernetes` client is invoked with the RIGHT arguments and that the
adapter maps 404/409/terminal-Job-status shapes correctly. `JobSpec`/`PvcSpec`
mapping proof lives in `test_kubernetes_job_mapping.py` (PR2a). Live-cluster
proof that a real Job actually runs and a real scanner-labelled Pod's egress
is blocked lives in `tests/integration/test_kubernetes_client_job_runner_live.py`
(PR2c, tasks 2.14-2.16).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client import ApiException  # type: ignore[import-untyped]

from orchestrator.domain.ports.kubernetes_job_runner_port import (
    JobOutcome,
    JobSpec,
    PvcSpec,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_job_runner import (
    KubernetesClientJobRunner,
)

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


def _api_exception(status: int) -> ApiException:
    return ApiException(status=status)


def _job_runner(
    batch_api: MagicMock | None = None,
    core_api: MagicMock | None = None,
) -> tuple[KubernetesClientJobRunner, MagicMock, MagicMock]:
    batch = batch_api if batch_api is not None else MagicMock()
    core = core_api if core_api is not None else MagicMock()
    runner = KubernetesClientJobRunner(
        batch,
        core,
        poll_interval_seconds=0,
        now_fn=_FakeClock(),
        sleep_fn=lambda _seconds: None,
    )
    return runner, batch, core


class _FakeClock:
    """Injected monotonic clock: advances by 1 on every read after the first."""

    def __init__(self) -> None:
        self._value = 0.0

    def __call__(self) -> float:
        current = self._value
        self._value += 1.0
        return current


# ---------------------------------------------------------------------------
# 2.7 get/create 404/409
# ---------------------------------------------------------------------------


def test_get_pvc_returns_false_on_404() -> None:
    runner, _batch, core = _job_runner()
    core.read_namespaced_persistent_volume_claim.side_effect = _api_exception(404)

    assert runner.get_pvc(_NAMESPACE, "missing-pvc") is False


def test_get_pvc_reraises_non_404() -> None:
    runner, _batch, core = _job_runner()
    core.read_namespaced_persistent_volume_claim.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        runner.get_pvc(_NAMESPACE, "some-pvc")


def test_get_pvc_returns_true_when_found() -> None:
    runner, _batch, core = _job_runner()
    core.read_namespaced_persistent_volume_claim.return_value = MagicMock()

    assert runner.get_pvc(_NAMESPACE, "some-pvc") is True


def test_get_job_returns_false_on_404() -> None:
    runner, batch, _core = _job_runner()
    batch.read_namespaced_job.side_effect = _api_exception(404)

    assert runner.get_job(_NAMESPACE, "missing-job") is False


def test_create_pvc_treats_409_as_success() -> None:
    runner, _batch, core = _job_runner()
    core.create_namespaced_persistent_volume_claim.side_effect = _api_exception(409)

    runner.create_pvc(PvcSpec(name="p", namespace=_NAMESPACE, labels={}))  # must not raise


def test_create_pvc_reraises_non_409() -> None:
    runner, _batch, core = _job_runner()
    core.create_namespaced_persistent_volume_claim.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        runner.create_pvc(PvcSpec(name="p", namespace=_NAMESPACE, labels={}))


def test_create_job_treats_409_as_success() -> None:
    runner, batch, _core = _job_runner()
    batch.create_namespaced_job.side_effect = _api_exception(409)

    runner.create_job(_checkout_job_spec())  # must not raise


def test_create_job_reraises_non_409() -> None:
    runner, batch, _core = _job_runner()
    batch.create_namespaced_job.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        runner.create_job(_checkout_job_spec())


# ---------------------------------------------------------------------------
# 2.8 wait_for_job
# ---------------------------------------------------------------------------


def _status(
    *, succeeded: int = 0, failed: int = 0, conditions: list[MagicMock] | None = None
) -> MagicMock:
    status = MagicMock()
    status.succeeded = succeeded
    status.failed = failed
    status.conditions = conditions or []
    return status


def _condition(condition_type: str, status: str = "True", reason: str | None = None) -> MagicMock:
    condition = MagicMock()
    condition.type = condition_type
    condition.status = status
    condition.reason = reason
    return condition


def test_wait_for_job_polls_until_succeeded_count_reaches_one() -> None:
    runner, batch, _core = _job_runner()
    batch.read_namespaced_job_status.side_effect = [
        MagicMock(status=_status()),
        MagicMock(status=_status()),
        MagicMock(status=_status(succeeded=1)),
    ]

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=True, failed=False, timed_out=False)
    assert batch.read_namespaced_job_status.call_count == 3


def test_wait_for_job_terminal_on_complete_condition() -> None:
    runner, batch, _core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(
        status=_status(conditions=[_condition("Complete")])
    )

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=True, failed=False, timed_out=False)


def test_wait_for_job_terminal_on_failed_count() -> None:
    runner, batch, _core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(status=_status(failed=1))

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=False, failed=True, timed_out=False)


def test_wait_for_job_deadline_exceeded_condition_is_timed_out() -> None:
    runner, batch, _core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(
        status=_status(failed=1, conditions=[_condition("Failed", reason="DeadlineExceeded")])
    )

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=False, failed=True, timed_out=True)


def test_wait_for_job_returns_timed_out_when_client_deadline_elapses() -> None:
    batch = MagicMock()
    batch.read_namespaced_job_status.return_value = MagicMock(status=_status())
    core = MagicMock()
    clock = iter([0.0, 100.0])
    runner = KubernetesClientJobRunner(
        batch,
        core,
        poll_interval_seconds=0,
        now_fn=lambda: next(clock),
        sleep_fn=lambda _seconds: None,
    )

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=10)

    assert outcome == JobOutcome(succeeded=False, failed=True, timed_out=True)


# ---------------------------------------------------------------------------
# 5.3/5.4 wait_for_job populates JobOutcome.exit_code (k8s-backend-enable PR5)
# ---------------------------------------------------------------------------


def _terminated_pod(name: str, creation_timestamp: int, exit_code: int) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.creation_timestamp = creation_timestamp
    pod.status.container_statuses[0].state.terminated.exit_code = exit_code
    return pod


def test_wait_for_job_populates_exit_code_from_the_newest_pods_terminated_container() -> None:
    runner, batch, core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(status=_status(failed=1))
    core.list_namespaced_pod.return_value = MagicMock(
        items=[
            _terminated_pod("job-pod-old", 1, exit_code=0),
            _terminated_pod("job-pod-new", 2, exit_code=2),
        ]
    )

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=False, failed=True, timed_out=False, exit_code=2)
    core.list_namespaced_pod.assert_called_with(
        _NAMESPACE, label_selector="batch.kubernetes.io/job-name=job"
    )


def test_wait_for_job_exit_code_is_none_when_the_pod_is_not_yet_observable() -> None:
    runner, batch, core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(status=_status(succeeded=1))
    core.list_namespaced_pod.return_value = MagicMock(items=[])

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=True, failed=False, timed_out=False, exit_code=None)


def test_wait_for_job_exit_code_lookup_never_raises_on_transport_failure() -> None:
    runner, batch, core = _job_runner()
    batch.read_namespaced_job_status.return_value = MagicMock(status=_status(succeeded=1))
    core.list_namespaced_pod.side_effect = _api_exception(500)

    outcome = runner.wait_for_job(_NAMESPACE, "job", timeout_seconds=60)

    assert outcome == JobOutcome(succeeded=True, failed=False, timed_out=False, exit_code=None)


# ---------------------------------------------------------------------------
# 2.9 get_job_logs
# ---------------------------------------------------------------------------


def _pod(name: str, creation_timestamp: int) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.creation_timestamp = creation_timestamp
    return pod


def test_get_job_logs_reads_from_the_newest_pod_by_creation_timestamp() -> None:
    runner, _batch, core = _job_runner()
    core.list_namespaced_pod.return_value = MagicMock(
        items=[_pod("job-pod-old", 1), _pod("job-pod-new", 2)]
    )
    core.read_namespaced_pod_log.return_value = "log output"

    log = runner.get_job_logs(_NAMESPACE, "job", max_bytes=65_536)

    assert log == "log output"
    core.list_namespaced_pod.assert_called_once_with(
        _NAMESPACE, label_selector="batch.kubernetes.io/job-name=job"
    )
    core.read_namespaced_pod_log.assert_called_once_with(
        "job-pod-new", _NAMESPACE, limit_bytes=65_536
    )


def test_get_job_logs_returns_empty_string_when_no_pod_found() -> None:
    runner, _batch, core = _job_runner()
    core.list_namespaced_pod.return_value = MagicMock(items=[])

    assert runner.get_job_logs(_NAMESPACE, "job", max_bytes=65_536) == ""
    core.read_namespaced_pod_log.assert_not_called()


def test_get_job_logs_returns_empty_string_on_404_never_raises() -> None:
    runner, _batch, core = _job_runner()
    core.list_namespaced_pod.side_effect = _api_exception(404)

    assert runner.get_job_logs(_NAMESPACE, "job", max_bytes=65_536) == ""


def test_get_job_logs_truncates_to_max_bytes() -> None:
    runner, _batch, core = _job_runner()
    core.list_namespaced_pod.return_value = MagicMock(items=[_pod("job-pod", 1)])
    core.read_namespaced_pod_log.return_value = "x" * 100

    assert runner.get_job_logs(_NAMESPACE, "job", max_bytes=10) == "x" * 10


# ---------------------------------------------------------------------------
# 2.10 delete uses Background propagation, 404 is a no-op
# ---------------------------------------------------------------------------


def test_delete_job_uses_background_propagation_policy() -> None:
    runner, batch, _core = _job_runner()

    runner.delete_job(_NAMESPACE, "job")

    batch.delete_namespaced_job.assert_called_once_with(
        "job", _NAMESPACE, propagation_policy="Background"
    )


def test_delete_job_is_a_no_op_on_404() -> None:
    runner, batch, _core = _job_runner()
    batch.delete_namespaced_job.side_effect = _api_exception(404)

    runner.delete_job(_NAMESPACE, "job")  # must not raise


def test_delete_job_reraises_non_404() -> None:
    runner, batch, _core = _job_runner()
    batch.delete_namespaced_job.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        runner.delete_job(_NAMESPACE, "job")


def test_delete_pvc_is_a_no_op_on_404() -> None:
    runner, _batch, core = _job_runner()
    core.delete_namespaced_persistent_volume_claim.side_effect = _api_exception(404)

    runner.delete_pvc(_NAMESPACE, "pvc")  # must not raise


# ---------------------------------------------------------------------------
# 2.11 list_job_names / list_pvc_names
# ---------------------------------------------------------------------------


def test_list_job_names_maps_items_to_names() -> None:
    runner, batch, _core = _job_runner()
    batch.list_namespaced_job.return_value = MagicMock(items=[_pod("job-a", 1), _pod("job-b", 2)])

    assert runner.list_job_names(_NAMESPACE) == ["job-a", "job-b"]


def test_list_pvc_names_maps_items_to_names() -> None:
    runner, _batch, core = _job_runner()
    core.list_namespaced_persistent_volume_claim.return_value = MagicMock(
        items=[_pod("pvc-a", 1)]
    )

    assert runner.list_pvc_names(_NAMESPACE) == ["pvc-a"]
