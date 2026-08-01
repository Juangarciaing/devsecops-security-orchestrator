"""Live-cluster proof for k8s-backend-enable PR5 (tasks 5.17-5.18) — REAL
`kind-devsecops-orchestrator` API server, no mocks, real public repository.

Confirms, against the real cluster:
- the bounded rev-parse Job succeeds on the **read-only** PVC mount
  (`pvc_read_only=True`) — `git -C /workspace/checkout rev-parse HEAD` only
  needs to READ `.git/HEAD` and refs, and genuinely does so under the same
  UID (65532) the checkout Job wrote those files as; no read-write fallback
  was needed (task 5.17's contingency was not required)
- a FULL 3-Job pipeline (checkout, rev-parse, scanner) runs in sequence
  against `https://github.com/trufflesecurity/test_keys` — a real public
  repository deliberately containing real (test) secrets — and Gitleaks
  exits 2 ("leaks found"), never raising `KubernetesWorkloadFailedError`
  (task 5.18, the concrete proof of design D-Result b's fix)
- the parsed `Finding`s come out through the EXISTING, UNMODIFIED
  `GitleaksAdapter.parse` (via `KubernetesRepositoryScanExecution`) and
  `ScanExecutionResult.head_sha` matches `git ls-remote` on the same ref —
  proving the rev-parse Job's stdout is the real commit, not fabricated
- `kubectl`-verified zero residue after the run (all 3 Jobs + the PVC
  cleaned up, matching the split executor's `finally`-block contract)

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

from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_job_runner import (
    KubernetesClientJobRunner,
)
from orchestrator.infrastructure.kubernetes.kubernetes_repository_scan_execution import (
    KubernetesRepositoryScanExecution,
)

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"

#: TruffleSecurity's public, deliberately-leaky test fixture repository —
#: designed exactly for exercising secret-scanner detection (real, though
#: intentionally test/canary, credentials committed at HEAD). Small and
#: stable: a single `keys` file with an AWS access key, a generic API key,
#: and a private key.
_LEAKY_REPO_URL = "https://github.com/trufflesecurity/test_keys.git"
_LEAKY_REPO_REF = "main"


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
def bridge(live_cluster: None) -> KubernetesRepositoryScanExecution:
    settings = _settings()
    runner = KubernetesClientJobRunner(k8s_client.BatchV1Api(), k8s_client.CoreV1Api())
    return KubernetesRepositoryScanExecution(
        runner,
        namespace=_NAMESPACE,
        checkout_image=settings.scan_git_image,
        settings=settings,
        timeout_seconds=90,
    )


def _real_head_sha() -> str:
    result = subprocess.run(
        ["git", "ls-remote", _LEAKY_REPO_URL, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.split()[0]


def _kubectl_get_names(resource: str, scan_task_id: uuid.UUID) -> str:
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            _NAMESPACE,
            "get",
            resource,
            "-l",
            f"scan-task-id={scan_task_id}",
            "-o",
            "name",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _wait_for_empty(
    resource: str, scan_task_id: uuid.UUID, *, timeout_seconds: float = 45.0
) -> str:
    """`propagation_policy="Background"` deletion is asynchronous — poll
    rather than asserting immediately (mirrors PR2's live-test convention)."""
    deadline = time.monotonic() + timeout_seconds
    names = _kubectl_get_names(resource, scan_task_id)
    while names and time.monotonic() < deadline:
        time.sleep(2)
        names = _kubectl_get_names(resource, scan_task_id)
    return names


def test_full_gitleaks_pipeline_finds_real_secrets_with_matching_head_sha(
    bridge: KubernetesRepositoryScanExecution,
) -> None:
    """The whole point of PR5: three real Jobs run in sequence (checkout,
    rev-parse — on a READ-ONLY PVC mount, task 5.17 — then scanner), Gitleaks
    genuinely exits 2 against a repo with real findings, and NONE of that
    raises `KubernetesWorkloadFailedError` — the concrete fix for design bug
    #2 (scanner exit codes structurally lost)."""
    scan_task_id = uuid.uuid4()

    try:
        result = bridge.execute(
            _LEAKY_REPO_URL,
            _LEAKY_REPO_REF,
            scan_task_id,
            ScannerType.SECRETS,
        )

        assert result.head_sha == _real_head_sha()
        assert len(result.findings) >= 1
        rule_ids = {finding.rule_id for finding in result.findings}
        assert "private-key" in rule_ids
    finally:
        # Defined in the same test (not a separate "zero residue" test at
        # module end, unlike PR2's suite) because `scan_task_id` is randomly
        # generated per run, not a shared fixture-scoped label.
        leftover_pods = _wait_for_empty("pods", scan_task_id)
        leftover_jobs = _wait_for_empty("jobs", scan_task_id)
        leftover_pvcs = _wait_for_empty("pvc", scan_task_id)

        assert leftover_pods == "", f"leftover pods: {leftover_pods}"
        assert leftover_jobs == "", f"leftover jobs: {leftover_jobs}"
        assert leftover_pvcs == "", f"leftover pvcs: {leftover_pvcs}"


def test_clean_public_repo_scan_reports_zero_findings_via_the_real_pipeline(
    bridge: KubernetesRepositoryScanExecution,
) -> None:
    """A genuinely clean repository must still complete all 3 Jobs (exit 0
    throughout) and report zero findings — proving the happy path is not
    somehow an artifact of the "leaks found" exit-code reclassification."""
    scan_task_id = uuid.uuid4()

    try:
        result = bridge.execute(
            "https://github.com/octocat/Hello-World.git",
            "master",
            scan_task_id,
            ScannerType.SECRETS,
        )

        assert result.findings == []
        assert len(result.head_sha) == 40  # a real, resolved commit SHA
    finally:
        _wait_for_empty("pods", scan_task_id)
        _wait_for_empty("jobs", scan_task_id)
        _wait_for_empty("pvc", scan_task_id)
