"""Live-cluster proof for k8s-backend-enable PR2 (tasks 2.14-2.16) — REAL
`kind-devsecops-orchestrator` API server, no mocks.

Confirms, against the real cluster:
- a real PVC binds under `WaitForFirstConsumer` and a real Job create → poll →
  logs → delete round-trip completes, with `kubectl`-verified zero residue
- `args`-not-`command` mapping (design D-Argv #1) is genuinely exercised: an
  image WITH a real ENTRYPOINT (`alpine/git`) only runs correctly when its
  argv lands on `V1Container.args` — mapping it to `command` would make the
  Pod try to exec a literal `--version` binary and fail instantly
- a real Pod that exits non-zero is reported as `JobOutcome` DATA
  (`failed=True`), never raised by the adapter — proving "the adapter never
  classifies" (design D-JobRunner) against a genuinely-run Pod, not a mock
- the client-side poll deadline elapses before the Job's own
  `activeDeadlineSeconds` and is reported `timed_out=True`
- a real scanner-labelled Pod's egress is genuinely blocked by Calico
  (task 2.15), while a real checkout-labelled Pod's egress to `:443` is
  genuinely allowed — proving the Pod-template label fix (D-Argv #2) closes
  egress for real, not just in a mapping-test assertion

Skips automatically if `kind-devsecops-orchestrator` is not reachable —
mirrors `test_kubernetes_client_factory_live.py`'s convention.
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
    return f"pr2live-{_RUN_ID}-{suffix}"


def _labels(component: str) -> dict[str, str]:
    return {**_BASE_LABELS, "component": component}


def _job_spec(
    *,
    name: str,
    component: str,
    image: str,
    command: list[str],
    pvc_name: str,
    timeout_seconds: int = 60,
) -> JobSpec:
    return JobSpec(
        name=name,
        namespace=_NAMESPACE,
        labels=_labels(component),
        image=image,
        command=command,
        pvc_name=pvc_name,
        pvc_read_only=(component != "checkout"),
        allow_network_egress=(component == "checkout"),
        timeout_seconds=timeout_seconds,
    )


def _cleanup(
    job_runner: KubernetesClientJobRunner, *, job_name: str | None, pvc_name: str | None
) -> None:
    if job_name is not None:
        job_runner.delete_job(_NAMESPACE, job_name)
    if pvc_name is not None:
        job_runner.delete_pvc(_NAMESPACE, pvc_name)


def _kubectl_get_names(resource: str) -> str:
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            _NAMESPACE,
            "get",
            resource,
            "-l",
            f"test-run={_RUN_ID}",
            "-o",
            "name",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _wait_for_empty(resource: str, *, timeout_seconds: float = 45.0) -> str:
    """`propagation_policy="Background"` deletion is asynchronous — the API
    server accepts the delete immediately but the garbage collector reaps
    dependent Pods over the following seconds (bounded by the Pod's
    termination grace period). Poll rather than asserting immediately."""
    deadline = time.monotonic() + timeout_seconds
    names = _kubectl_get_names(resource)
    while names and time.monotonic() < deadline:
        time.sleep(2)
        names = _kubectl_get_names(resource)
    return names


def test_pvc_binds_and_args_not_command_mapping_runs_the_real_entrypoint(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """Real PVC + real Job create→poll→logs→delete round trip. Uses
    `alpine/git`, an image WITH a real ENTRYPOINT, and passes ONLY
    `--version` as `JobSpec.command` — if that landed on `V1Container.command`
    instead of `.args`, the Pod would try to exec a binary literally named
    `--version` and fail instantly instead of running `git --version`."""
    pvc_name = _name("pvc-a")
    job_name = _name("checkout-a")
    job_runner.create_pvc(
        PvcSpec(
            name=pvc_name,
            namespace=_NAMESPACE,
            labels=_BASE_LABELS,
            storage_class_name=_STORAGE_CLASS,
        )
    )
    try:
        spec = _job_spec(
            name=job_name,
            component="checkout",
            image="alpine/git:v2.45.2",
            command=["--version"],
            pvc_name=pvc_name,
        )
        job_runner.create_job(spec)
        outcome = job_runner.wait_for_job(_NAMESPACE, job_name, timeout_seconds=60)
        logs = job_runner.get_job_logs(_NAMESPACE, job_name, max_bytes=65_536)

        assert outcome.succeeded is True
        assert outcome.failed is False
        assert "git version 2.45.2" in logs
    finally:
        _cleanup(job_runner, job_name=job_name, pvc_name=pvc_name)


def test_non_zero_exit_is_reported_as_job_outcome_data_not_raised(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """A real scanner Pod that exits non-zero (simulating a scanner that
    found something, e.g. Gitleaks' `--exit-code=2`) must come back as
    `JobOutcome(failed=True)` DATA from `wait_for_job` — the adapter itself
    must not raise. Classifying that as terminal-vs-data is
    `KubernetesSplitScanExecution`'s job (PR5's `scanner_exit_codes_are_data`),
    never this adapter's."""
    pvc_name = _name("pvc-b")
    job_name = _name("scanner-b")
    job_runner.create_pvc(
        PvcSpec(
            name=pvc_name,
            namespace=_NAMESPACE,
            labels=_BASE_LABELS,
            storage_class_name=_STORAGE_CLASS,
        )
    )
    try:
        spec = _job_spec(
            name=job_name,
            component="scanner",
            image="alpine:3.20",
            command=["sh", "-c", "echo simulating scanner findings; exit 2"],
            pvc_name=pvc_name,
        )
        job_runner.create_job(spec)
        outcome = job_runner.wait_for_job(_NAMESPACE, job_name, timeout_seconds=60)
        logs = job_runner.get_job_logs(_NAMESPACE, job_name, max_bytes=65_536)

        assert outcome.succeeded is False
        assert outcome.failed is True
        assert outcome.timed_out is False
        assert "simulating scanner findings" in logs
    finally:
        _cleanup(job_runner, job_name=job_name, pvc_name=pvc_name)


def test_client_side_deadline_elapses_before_active_deadline_seconds(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """`timeout_seconds=5` (so `activeDeadlineSeconds=35`) against a Pod that
    sleeps far longer than either — the CLIENT poll deadline must elapse and
    report `timed_out=True` well before Kubernetes' own server-side deadline
    would ever fire."""
    pvc_name = _name("pvc-c")
    job_name = _name("scanner-c")
    job_runner.create_pvc(
        PvcSpec(
            name=pvc_name,
            namespace=_NAMESPACE,
            labels=_BASE_LABELS,
            storage_class_name=_STORAGE_CLASS,
        )
    )
    try:
        spec = _job_spec(
            name=job_name,
            component="scanner",
            image="alpine:3.20",
            command=["sh", "-c", "sleep 300"],
            pvc_name=pvc_name,
            timeout_seconds=5,
        )
        start = time.monotonic()
        job_runner.create_job(spec)
        outcome = job_runner.wait_for_job(_NAMESPACE, job_name, timeout_seconds=5)
        elapsed = time.monotonic() - start

        assert outcome.timed_out is True
        assert outcome.failed is True
        assert elapsed < 30  # genuinely client-bounded, not the 35s server deadline
    finally:
        _cleanup(job_runner, job_name=job_name, pvc_name=pvc_name)


def test_scanner_egress_is_blocked_and_checkout_egress_is_allowed_by_real_calico(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """Live isolation proof (task 2.15): a scanner-labelled Pod's outbound
    TCP connect must FAIL under the real, enforced `scanner-egress`
    total-deny policy, while a checkout-labelled Pod's outbound `:443`
    connect must SUCCEED under `checkout-egress`'s explicit allow — proving
    the Pod-template label fix (D-Argv #2) actually closes egress, not just
    the mapping test."""
    pvc_name = _name("pvc-d")
    scanner_job = _name("scanner-d")
    checkout_job = _name("checkout-d")
    probe = "nc -z -w 5 1.1.1.1 443 && echo REACHED || echo BLOCKED"
    job_runner.create_pvc(
        PvcSpec(
            name=pvc_name,
            namespace=_NAMESPACE,
            labels=_BASE_LABELS,
            storage_class_name=_STORAGE_CLASS,
        )
    )
    try:
        job_runner.create_job(
            _job_spec(
                name=scanner_job,
                component="scanner",
                image="alpine:3.20",
                command=["sh", "-c", probe],
                pvc_name=pvc_name,
            )
        )
        job_runner.create_job(
            _job_spec(
                name=checkout_job,
                component="checkout",
                image="alpine:3.20",
                command=["sh", "-c", probe],
                pvc_name=pvc_name,
            )
        )
        scanner_outcome = job_runner.wait_for_job(_NAMESPACE, scanner_job, timeout_seconds=60)
        checkout_outcome = job_runner.wait_for_job(_NAMESPACE, checkout_job, timeout_seconds=60)
        scanner_logs = job_runner.get_job_logs(_NAMESPACE, scanner_job, max_bytes=65_536)
        checkout_logs = job_runner.get_job_logs(_NAMESPACE, checkout_job, max_bytes=65_536)

        assert "BLOCKED" in scanner_logs
        assert scanner_outcome.succeeded is True  # `nc` fails -> `||` branch exits 0
        assert "REACHED" in checkout_logs
        assert checkout_outcome.succeeded is True
    finally:
        _cleanup(job_runner, job_name=scanner_job, pvc_name=None)
        _cleanup(job_runner, job_name=checkout_job, pvc_name=pvc_name)


def test_cluster_has_zero_residue_from_this_modules_tests(
    job_runner: KubernetesClientJobRunner,
) -> None:
    """Defined last in this file (pytest runs a module's tests in definition
    order), after every resource-creating test above has already run its own
    `finally`-block cleanup: `kubectl`-verified proof that success, failure,
    and timeout paths all leave zero Jobs/Pods/PVCs behind for this run's
    unique `test-run` label."""
    leftover_pods = _wait_for_empty("pods")
    leftover_jobs = _wait_for_empty("jobs")
    leftover_pvcs = _wait_for_empty("pvc")

    assert leftover_pods == "", f"leftover pods: {leftover_pods}"
    assert leftover_jobs == "", f"leftover jobs: {leftover_jobs}"
    assert leftover_pvcs == "", f"leftover pvcs: {leftover_pvcs}"
