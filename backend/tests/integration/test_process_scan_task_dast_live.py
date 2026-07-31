"""Live end-to-end proof for the DAST worker path (dast-scanner design D9,
PR7, task 7.5): `trigger_scan` -> `process_scan_task` -> REAL ZAP Docker
scan -> persisted `Finding`s -> `ScanRun`/`ScanTask` reach `COMPLETED`.

Complements `test_zap_dast_execution_live.py` (PR5, task 5.15), which
already proves `ZapDastDockerExecution` end to end against real Docker in
isolation. This file's job is different and non-redundant: prove the FULL
worker dispatch path this PR added — `_load_and_start`'s target-subject
branch, the `dast_enabled` gate, `_run_target_scan`, and
`_complete_target_scan` — against a REAL Postgres AND a REAL Docker daemon,
driving `process_scan_task` exactly as `test_process_scan_task.py` drives it
(`Task.apply()`, no live broker needed).

Needs BOTH a live Docker socket AND live Postgres. Skips automatically if no
Docker socket is reachable, matching this repo's other live-scanner
integration tests. Bypasses the DNS-resolution half of the SSRF guard for
the same documented reason as `test_zap_dast_execution_live.py` (every local
Docker network lives inside a blocked private CIDR range) — the guard's
full CIDR matrix is already exhaustively unit-tested elsewhere.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import datetime

import docker
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.application.use_cases.trigger_scan import trigger_scan
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.services.target_url_policy import validate_target_url_shape
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.container import zap_dast_execution
from orchestrator.infrastructure.container.dast_network import ensure_dast_network
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.scan_target import ScanTargetModel
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    SqlAlchemyScanTargetRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)


def _live_docker_client() -> docker.DockerClient:
    client = docker.from_env()
    client.ping()
    return client


@pytest.fixture
def docker_client(migrated_schema: None) -> Iterator[docker.DockerClient]:
    try:
        client = _live_docker_client()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no reachable Docker socket: {exc}")
    yield client
    client.close()


def _bypass_dns_blocklist_but_keep_real_shape_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real `validate_target_url_shape` still runs; only the DNS-resolution
    blocklist half of the guard is skipped — see module docstring."""

    async def _fake_resolve_and_authorize(url: str) -> str:
        validate_target_url_shape(url)
        return url

    monkeypatch.setattr(zap_dast_execution, "resolve_and_authorize", _fake_resolve_and_authorize)


async def _seed_target_and_trigger(
    target_url: str, name: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Register a `ScanTarget` and trigger a real DAST scan via the actual
    `trigger_scan` use case. Returns `(target_id, scan_run_id, scan_task_id)`.
    """
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            target = await SqlAlchemyScanTargetRepository(session).create(
                ScanTarget(
                    id=uuid.uuid4(),
                    name=name,
                    target_url=target_url,
                    is_active=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.commit()
            target_id = target.id

        async with sessionmaker() as session:
            run, created = await trigger_scan(
                SqlAlchemyCodeRepositoryRepository(session),
                SqlAlchemyScanRunRepository(session),
                SqlAlchemyScanTaskRepository(session),
                scanner_type=ScannerType.DAST,
                trigger="manual",
                triggered_by_user_id=None,
                scan_target_id=target_id,
                scan_target_port=SqlAlchemyScanTargetRepository(session),
            )
            await session.commit()
            assert created is True, "expected the first trigger to create a fresh ScanRun/ScanTask"
            run_id = run.id
            tasks = await SqlAlchemyScanTaskRepository(session).list_by_scan_run(run_id)
            task_id = tasks[0].id

        return target_id, run_id, task_id
    finally:
        await engine.dispose()


async def _load_final_state(
    scan_task_id: uuid.UUID, scan_run_id: uuid.UUID
) -> tuple[object, object, list[object]]:
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


async def _delete_scan_target(scan_target_id: uuid.UUID) -> None:
    """Cascades (`ondelete=CASCADE`) to the `ScanRun`/`ScanTask`/`Finding`
    rows this test created, so `migrated_schema`'s downgrade teardown keeps
    working regardless of outcome — same precedent as
    `test_finding_dedup_partial_index.py`/`test_process_scan_task.py`."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            await session.execute(
                delete(ScanTargetModel).where(ScanTargetModel.id == scan_target_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


def test_target_scan_trigger_through_worker_persists_real_zap_findings_end_to_end(
    docker_client: docker.DockerClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Imported lazily, matching `test_process_scan_task.py`'s established
    # convention: `workers/celery_app.py` resolves `Settings()` eagerly at
    # import time, so importing this at module top-level would fail
    # collection whenever no `.env` is present.
    from orchestrator.workers.tasks.process_scan import process_scan_task

    monkeypatch.setenv("DAST_ENABLED", "true")
    get_settings.cache_clear()
    _bypass_dns_blocklist_but_keep_real_shape_validation(monkeypatch)

    settings = get_settings()
    network_name = ensure_dast_network(docker_client, settings)

    target_container_name = f"dast-live-e2e-target-{uuid.uuid4().hex[:8]}"
    target_container = docker_client.containers.run(
        image="nginx:1.27-alpine",
        name=target_container_name,
        network=network_name,
        detach=True,
        remove=False,
    )

    target_id: uuid.UUID | None = None
    try:
        target_container.reload()
        assert target_container.status in {"running", "created"}
        target_url = f"http://{target_container_name}/"

        target_id, run_id, task_id = asyncio.run(
            _seed_target_and_trigger(target_url, target_container_name)
        )

        runner = DockerContainerRunner(client=docker_client)
        result = process_scan_task.apply(
            args=(str(task_id),),
            kwargs={"container_runner": runner, "docker_client": docker_client},
        )
        result.get()

        task, run, findings = asyncio.run(_load_final_state(task_id, run_id))
        assert task.status == ScanTaskStatus.COMPLETED  # type: ignore[attr-defined]
        assert task.error_message is None  # type: ignore[attr-defined]
        assert run.status == ScanRunStatus.COMPLETED  # type: ignore[attr-defined]
        assert run.commit_sha is None  # type: ignore[attr-defined] — never touched (D5)
        for finding in findings:
            assert finding.scan_task_id == task_id  # type: ignore[attr-defined]
            assert finding.scan_target_id == target_id  # type: ignore[attr-defined]
            assert finding.repository_id is None  # type: ignore[attr-defined]
        print(
            "\n[test_process_scan_task_dast_live] real trigger_scan -> "
            f"process_scan_task -> ZAP flow completed with {len(findings)} "
            "finding(s) persisted."
        )
    finally:
        target_container.remove(force=True)
        if target_id is not None:
            asyncio.run(_delete_scan_target(target_id))
