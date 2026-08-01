"""Live-cluster + live-Postgres proof for k8s-backend-enable PR6 (tasks
6.9-6.11) — the REAL `process_scan_task` Celery task, run through
`Task.apply()` exactly like `test_process_scan_task.py`'s Docker e2e suite,
but with `scan_execution_backend=kubernetes` routed all the way to a real
`kind-devsecops-orchestrator` API server. No bridge/adapter is exercised in
isolation here — this is the actual worker entry point end to end.

Confirms, against the real cluster AND a real database:
- a full happy-path repository scan (`https://github.com/trufflesecurity/
  test_keys.git`, a public repo with real, deliberately-committed test
  secrets) persists real `Finding`s and the resolved `head_sha` — task 6.9
- a credential-bearing repository routed through the Kubernetes backend
  fails deterministically with the bridge's exact `KubernetesPrivateRepositoryError`
  message, via `_mark_failed`, with ZERO cluster objects (Jobs/PVCs) ever
  created — task 6.10
- `scan_execution_backend="docker"` (the default) still produces the exact
  same behavior as `test_process_scan_task.py`'s existing happy-path test,
  with ZERO Kubernetes API client objects ever constructed — task 6.11

Skips the kubernetes-specific tests (6.9/6.10) automatically if
`kind-devsecops-orchestrator` is not reachable — mirrors this chain's other
live test files' convention. The docker byte-identical regression check
(6.11) is NOT gated on cluster reachability: it must always run, and proves
its "zero Kubernetes calls" claim by making even constructing a `kubernetes`
client API object raise.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from kubernetes import client as k8s_client
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import (
    CredentialKind,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.config.settings import Settings, get_settings
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
from tests.fakes.fake_container_runner import FakeContainerRunner

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"
_STORAGE_CLASS = "scan-workspace"
_NOW = datetime(2026, 1, 1)

#: Same public, deliberately-leaky test-fixture repository PR5's live bridge
#: test already trusts (task 5.18) — reused here so this file proves the
#: SAME real findings flow all the way through the real Celery task, not
#: just the bridge in isolation.
_LEAKY_REPO_URL = "https://github.com/trufflesecurity/test_keys.git"
_LEAKY_REPO_REF = "main"


def _kubernetes_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCAN_EXECUTION_BACKEND", "kubernetes")
    monkeypatch.setenv("KUBERNETES_NAMESPACE", _NAMESPACE)
    monkeypatch.setenv("KUBERNETES_STORAGE_CLASS_NAME", _STORAGE_CLASS)
    monkeypatch.setenv("KUBERNETES_KUBECONFIG_CONTEXT", _CONTEXT)
    monkeypatch.setenv("KUBERNETES_CNI_ENFORCES_NETWORK_POLICY", "true")
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def live_cluster() -> Iterator[None]:
    try:
        load_kubernetes_config(
            Settings(
                _env_file=None,
                database_url="postgresql://o:o@localhost/o",
                redis_url="redis://localhost:6379/0",
                secret_key="s",
                jwt_secret_key="j",
                kubernetes_kubeconfig_context=_CONTEXT,
            )
        )
        k8s_client.CoreV1Api().list_namespace(_request_timeout=5)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"kind-devsecops-orchestrator cluster not reachable: {exc}")
    yield


async def _seed_repository_task(
    *, clone_url: str, ref: str, credential_ciphertext: str | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a `CodeRepository` + pending `ScanRun`/`ScanTask`
    (`scanner_type=SECRETS`). Returns `(task_id, scan_run_id)`."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = await SqlAlchemyCodeRepositoryRepository(session).create(
                CodeRepository(
                    id=uuid.uuid4(),
                    provider=RepositoryProvider.GITHUB,
                    owner="k8s-live",
                    name=f"repo-{uuid.uuid4().hex[:8]}",
                    clone_url=clone_url,
                    default_branch=ref,
                    credential_kind=(
                        CredentialKind.PERSONAL_ACCESS_TOKEN
                        if credential_ciphertext is not None
                        else None
                    ),
                    credential_ciphertext=credential_ciphertext,
                    is_active=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            run = await SqlAlchemyScanRunRepository(session).create(
                ScanRun(
                    id=uuid.uuid4(),
                    repository_id=repository_id,
                    status=ScanRunStatus.PENDING,
                    trigger="manual",
                    commit_sha=ref,
                    ref=ref,
                    created_at=_NOW,
                )
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).create(
                ScanTask(
                    id=uuid.uuid4(),
                    scan_run_id=run_id,
                    scanner_type=ScannerType.SECRETS,
                    status=ScanTaskStatus.PENDING,
                )
            )
            await session.commit()
            task_id = task.id

        return task_id, run_id
    finally:
        await engine.dispose()


async def _load_state(
    scan_task_id: uuid.UUID, scan_run_id: uuid.UUID
) -> tuple[ScanTask, ScanRun, list[object]]:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).get_by_id(scan_task_id)
            run = await SqlAlchemyScanRunRepository(session).get_by_id(scan_run_id)
            findings = await SqlAlchemyFindingRepository(session).list_by_scan_task(scan_task_id)
            assert task is not None
            assert run is not None
            return task, run, list(findings)
    finally:
        await engine.dispose()


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
    rather than asserting immediately (mirrors PR2/PR5's live-test
    convention)."""
    deadline = time.monotonic() + timeout_seconds
    names = _kubectl_get_names(resource, scan_task_id)
    while names and time.monotonic() < deadline:
        time.sleep(2)
        names = _kubectl_get_names(resource, scan_task_id)
    return names


def test_process_scan_task_kubernetes_backend_persists_real_findings_and_head_sha(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch, live_cluster: None
) -> None:
    """Task 6.9: the REAL `process_scan_task` (not the bridge in isolation)
    with `scan_execution_backend="kubernetes"` runs the full 3-Job pipeline
    against a real public repository, persists real `Finding`s, and resolves
    `ScanRun.commit_sha` to the real HEAD SHA."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    _kubernetes_env(monkeypatch)
    task_id, run_id = asyncio.run(
        _seed_repository_task(clone_url=_LEAKY_REPO_URL, ref=_LEAKY_REPO_REF)
    )

    try:
        result = process_scan_task.apply(
            args=(str(task_id),), kwargs={"docker_client": MagicMock()}
        )
        result.get()

        task, run, findings = asyncio.run(_load_state(task_id, run_id))
        assert task.status == ScanTaskStatus.COMPLETED
        assert task.error_message is None
        assert run.status == ScanRunStatus.COMPLETED
        assert run.commit_sha == _real_head_sha()
        assert len(findings) >= 1
        rule_ids = {f.rule_id for f in findings}  # type: ignore[attr-defined]
        assert "private-key" in rule_ids
    finally:
        leftover_pods = _wait_for_empty("pods", task_id)
        leftover_jobs = _wait_for_empty("jobs", task_id)
        leftover_pvcs = _wait_for_empty("pvc", task_id)
        assert leftover_pods == "", f"leftover pods: {leftover_pods}"
        assert leftover_jobs == "", f"leftover jobs: {leftover_jobs}"
        assert leftover_pvcs == "", f"leftover pvcs: {leftover_pvcs}"


def test_process_scan_task_kubernetes_backend_private_repo_fails_with_zero_cluster_objects(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch, live_cluster: None
) -> None:
    """Task 6.10: a credential-bearing repository routed through the
    Kubernetes backend fails `failed` with the bridge's EXACT
    `KubernetesPrivateRepositoryError` message, and creates ZERO cluster
    objects (kubectl-verified, keyed on `scan-task-id`)."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    _kubernetes_env(monkeypatch)
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    ciphertext = (
        FernetCredentialStore(encryption_key=key)
        .seal("ghp_supersecrettoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
        .ciphertext
    )

    task_id, run_id = asyncio.run(
        _seed_repository_task(
            clone_url="https://example.com/acme-scan/private-widgets.git",
            ref="main",
            credential_ciphertext=ciphertext,
        )
    )

    result = process_scan_task.apply(args=(str(task_id),), kwargs={"docker_client": MagicMock()})
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message == (
        "the Kubernetes backend supports public repositories only; "
        "Secret projection into the checkout Job is a separate security design"
    )
    assert run.status == ScanRunStatus.FAILED
    assert len(findings) == 0

    assert _kubectl_get_names("jobs", task_id) == ""
    assert _kubectl_get_names("pvc", task_id) == ""


def test_process_scan_task_docker_backend_is_byte_identical_with_zero_kubernetes_api_calls(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 6.11: `scan_execution_backend="docker"` (the default — no env
    override here) produces the exact same happy-path outcome as
    `test_process_scan_task.py`'s existing Docker e2e test, and constructs
    ZERO `kubernetes` client API objects — proven by making every one of the
    four client classes `create_kubernetes_scan_execution` would need explode
    if ever instantiated. NOT gated on live cluster reachability: this
    regression proof must always run."""
    from orchestrator.workers.tasks import process_scan
    from orchestrator.workers.tasks.process_scan import process_scan_task

    def _exploding_client_class(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "a kubernetes client API object must never be constructed for "
            "scan_execution_backend='docker'"
        )

    for client_class_name in ("BatchV1Api", "CoreV1Api", "StorageV1Api", "NetworkingV1Api"):
        monkeypatch.setattr(k8s_client, client_class_name, _exploding_client_class)

    def _exploding_kubernetes_factory(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "create_kubernetes_scan_execution must never be called for "
            "scan_execution_backend='docker'"
        )

    monkeypatch.setattr(
        process_scan, "create_kubernetes_scan_execution", _exploding_kubernetes_factory
    )

    task_id, run_id = asyncio.run(
        _seed_repository_task(clone_url="https://example.com/acme-scan/widgets.git", ref="main")
    )

    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
    )
    docker_client = MagicMock()

    result = process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    )
    result.get()

    task, run, findings = asyncio.run(_load_state(task_id, run_id))
    assert task.status == ScanTaskStatus.COMPLETED
    assert task.error_message is None
    assert run.status == ScanRunStatus.COMPLETED
    assert run.commit_sha == "deadbeef1234"
    assert len(findings) == 0
    assert len(fake_runner.calls) == 3  # clone, rev-parse, gitleaks — unchanged
