"""Acceptance tests for `/api/v1/targets` — `ScanTarget` CRUD + RBAC +
`POST /{target_id}/scans` DAST trigger (dast-scanner PR6, `routers/targets.py`).

Mirrors `test_repositories_api.py`'s `_run_with_client` convention (a real
app + live-DB-backed httpx client) and `test_scans_api.py`'s `_DelaySpy`
convention for router-level trigger tests (proves the HTTP layer reaches
`trigger_scan`/enqueues without a live Celery worker or Redis; no ZAP
container ever runs here — that live-Docker proof already exists elsewhere).

All routes require `get_current_user` (member or admin) except `DELETE`,
which additionally requires `require_role(ADMIN)` — read straight off
`routers/targets.py`'s own docstring/dependencies.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.api.main import create_app
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus, UserRole
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_target import ScanTargetModel
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    SqlAlchemyScanTargetRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.security.jwt import create_access_token
from orchestrator.infrastructure.security.password_hasher import hash_password

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive timestamp columns


async def _seed_user(
    sessionmaker: async_sessionmaker[AsyncSession], email: str, role: UserRole
) -> User:
    async with sessionmaker() as session:
        repository = SqlAlchemyUserRepository(session)
        created = await repository.create(
            User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password("correct-horse"),
                role=role,
                is_active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await session.commit()
        return created


async def _seed_target(
    sessionmaker: async_sessionmaker[AsyncSession],
    name: str,
    target_url: str,
    is_active: bool = True,
) -> ScanTarget:
    async with sessionmaker() as session:
        repository = SqlAlchemyScanTargetRepository(session)
        created = await repository.create(
            ScanTarget(
                id=uuid.uuid4(),
                name=name,
                target_url=target_url,
                is_active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        if not is_active:
            await repository.soft_delete(created.id)
            created.is_active = False
        await session.commit()
        return created


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _set_dast_enabled(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Mirrors `test_repositories_api.py`'s `_with_credential_key` mechanism —
    the only settings-override pattern this repo's integration tests use: an
    env var via `monkeypatch` + `get_settings.cache_clear()` (never a
    `dependency_overrides` swap, since `settings` is read directly, not
    injected via `Depends`)."""
    monkeypatch.setenv("DAST_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


async def _run_with_client(scenario: object, delay_spy: object | None = None) -> None:
    """Build a live-DB-backed app + client, run `scenario(client, sessionmaker)`, tear down.

    When `delay_spy` is given, monkeypatches `process_scan_task.delay`
    directly on the shared Celery task singleton for the scenario's
    duration, then restores it — identical mechanism to
    `test_scans_api.py::_run_with_client`.
    """
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_db_session] = _override

    original_delay = None
    process_scan_task = None
    if delay_spy is not None:
        from orchestrator.workers.tasks.process_scan import process_scan_task

        original_delay = process_scan_task.delay
        process_scan_task.delay = delay_spy  # type: ignore[method-assign]

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client, sessionmaker)  # type: ignore[operator]
    finally:
        if delay_spy is not None and process_scan_task is not None:
            process_scan_task.delay = original_delay  # type: ignore[method-assign]
        await engine.dispose()


class _DelaySpy:
    """Records `.delay()` calls without touching Redis or running the task."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, scan_task_id: str) -> None:
        self.calls.append(scan_task_id)


async def _count_scan_runs_for_target(
    sessionmaker: async_sessionmaker[AsyncSession], target_id: uuid.UUID
) -> int:
    async with sessionmaker() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ScanRunModel)
            .where(ScanRunModel.scan_target_id == target_id)
        )
        return result.scalar_one()


async def _delete_target_cascade(
    sessionmaker: async_sessionmaker[AsyncSession], target_id: uuid.UUID
) -> None:
    """`scan_runs.scan_target_id`/`scan_tasks.scan_run_id` are both `ON DELETE
    CASCADE` — deleting the `ScanTargetModel` row cascades away any
    target-subject `ScanRun`/`ScanTask` rows created during a test. Mandatory
    cleanup for any test that creates a real target-subject `ScanRun`: the
    `migrated_schema` fixture's teardown runs `alembic downgrade base`, which
    re-adds `NOT NULL` to `scan_runs.repository_id` — impossible while a
    NULL-`repository_id` row survives (mirrors `test_repositories_api.py`'s
    noise-target cleanup for the same reason)."""
    async with sessionmaker() as session:
        await session.execute(delete(ScanTargetModel).where(ScanTargetModel.id == target_id))
        await session.commit()


def _create_payload(name: str = "prod-web") -> dict[str, str]:
    return {"name": name, "target_url": f"https://{uuid.uuid4()}.test"}


# ---------------------------------------------------------------------------
# 401 — no bearer token on every route
# ---------------------------------------------------------------------------


def test_post_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post("/api/v1/targets", json=_create_payload())

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_list_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get("/api/v1/targets")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get(f"/api/v1/targets/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_patch_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.patch(f"/api/v1/targets/{uuid.uuid4()}", json={"name": "x"})

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_delete_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.delete(f"/api/v1/targets/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_trigger_scan_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post(f"/api/v1/targets/{uuid.uuid4()}/scans")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST /targets — register
# ---------------------------------------------------------------------------


def test_post_creates_target_returns_201(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-post@example.com", UserRole.MEMBER)

        response = await client.post(
            "/api/v1/targets",
            json=_create_payload(name="post-target"),
            headers=_auth_header(member),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "post-target"
        assert body["is_active"] is True
        assert body["created_at"] is not None
        assert body["updated_at"] is not None

    asyncio.run(_run_with_client(scenario))


def test_post_duplicate_target_url_returns_409(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-dup@example.com", UserRole.MEMBER)
        target_url = f"https://{uuid.uuid4()}.test"
        await _seed_target(sessionmaker, "dup-target", target_url)

        response = await client.post(
            "/api/v1/targets",
            json={"name": "dup-target-2", "target_url": target_url},
            headers=_auth_header(member),
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# GET /targets — active-only listing
# ---------------------------------------------------------------------------


def test_list_excludes_inactive_targets(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-list@example.com", UserRole.MEMBER)
        active = await _seed_target(
            sessionmaker, "active-target", f"https://{uuid.uuid4()}.test"
        )
        inactive = await _seed_target(
            sessionmaker, "inactive-target", f"https://{uuid.uuid4()}.test", is_active=False
        )

        response = await client.get("/api/v1/targets", headers=_auth_header(member))

        assert response.status_code == 200
        ids = {item["id"] for item in response.json()}
        assert str(active.id) in ids
        assert str(inactive.id) not in ids

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# GET /targets/{id} — 404 on missing or inactive
# ---------------------------------------------------------------------------


def test_get_by_id_returns_active_target(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get@example.com", UserRole.MEMBER)
        target = await _seed_target(sessionmaker, "get-target", f"https://{uuid.uuid4()}.test")

        response = await client.get(f"/api/v1/targets/{target.id}", headers=_auth_header(member))

        assert response.status_code == 200
        assert response.json()["id"] == str(target.id)

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_inactive_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get-404@example.com", UserRole.MEMBER)
        target = await _seed_target(
            sessionmaker, "get-target-404", f"https://{uuid.uuid4()}.test", is_active=False
        )

        response = await client.get(f"/api/v1/targets/{target.id}", headers=_auth_header(member))

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_missing_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-get-missing@example.com", UserRole.MEMBER
        )

        response = await client.get(
            f"/api/v1/targets/{uuid.uuid4()}", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# PATCH /targets/{id} — partial update, 404 on inactive
# ---------------------------------------------------------------------------


def test_patch_partial_update_returns_200(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-patch@example.com", UserRole.MEMBER)
        target = await _seed_target(sessionmaker, "patch-target", f"https://{uuid.uuid4()}.test")

        response = await client.patch(
            f"/api/v1/targets/{target.id}",
            json={"name": "patched-name"},
            headers=_auth_header(member),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "patched-name"
        assert body["target_url"] == target.target_url

    asyncio.run(_run_with_client(scenario))


def test_patch_inactive_target_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-patch-inactive@example.com", UserRole.MEMBER
        )
        target = await _seed_target(
            sessionmaker, "patch-target-inactive", f"https://{uuid.uuid4()}.test", is_active=False
        )

        response = await client.patch(
            f"/api/v1/targets/{target.id}",
            json={"name": "should-not-apply"},
            headers=_auth_header(member),
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# DELETE /targets/{id} — admin-only, idempotent soft-delete
# ---------------------------------------------------------------------------


def test_delete_admin_deactivates_active_target(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete@example.com", UserRole.ADMIN)
        target = await _seed_target(sessionmaker, "delete-target", f"https://{uuid.uuid4()}.test")

        response = await client.delete(
            f"/api/v1/targets/{target.id}", headers=_auth_header(admin)
        )

        assert response.status_code == 204

        async with sessionmaker() as session:
            persisted = await SqlAlchemyScanTargetRepository(session).get_by_id(target.id)
            assert persisted is not None
            assert persisted.is_active is False

    asyncio.run(_run_with_client(scenario))


def test_delete_is_idempotent_on_already_inactive(migrated_schema: None) -> None:
    """Mirrors `test_repositories_api.py`'s `CodeRepository` precedent:
    `deactivate_scan_target` only raises `ScanTargetNotFoundError` (-> 404)
    when the id truly does not exist — an already-inactive target is an
    idempotent no-op success (204), not a 404."""

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete-idem@example.com", UserRole.ADMIN)
        target = await _seed_target(
            sessionmaker, "delete-target-idem", f"https://{uuid.uuid4()}.test", is_active=False
        )

        response = await client.delete(
            f"/api/v1/targets/{target.id}", headers=_auth_header(admin)
        )

        assert response.status_code == 204

    asyncio.run(_run_with_client(scenario))


def test_delete_missing_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete-404@example.com", UserRole.ADMIN)

        response = await client.delete(
            f"/api/v1/targets/{uuid.uuid4()}", headers=_auth_header(admin)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


def test_delete_member_forbidden_returns_403(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-delete-403@example.com", UserRole.MEMBER)
        target = await _seed_target(
            sessionmaker, "delete-target-403", f"https://{uuid.uuid4()}.test"
        )

        response = await client.delete(
            f"/api/v1/targets/{target.id}", headers=_auth_header(member)
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST /targets/{id}/scans — dast_enabled deny-by-default gate (design D9)
# ---------------------------------------------------------------------------


def test_trigger_scan_dast_disabled_returns_403_and_creates_no_scan_run(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single most important test in this file: `dast_enabled` deny-by-
    default is checked BEFORE `trigger_scan` is ever called (router source),
    so a real, active target still gets a 403 Problem response and zero
    `ScanRun` rows — not merely a rejected request, but a request that never
    reaches persistence at all."""
    _set_dast_enabled(monkeypatch, enabled=False)

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-dast-disabled@example.com", UserRole.MEMBER
        )
        target = await _seed_target(
            sessionmaker, "dast-disabled-target", f"https://{uuid.uuid4()}.test"
        )

        response = await client.post(
            f"/api/v1/targets/{target.id}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["detail"] == "DAST scanning is disabled (dast_enabled is unset)"

        assert await _count_scan_runs_for_target(sessionmaker, target.id) == 0

    asyncio.run(_run_with_client(scenario))


def test_trigger_scan_missing_target_returns_404(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_dast_enabled(monkeypatch, enabled=True)

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-trigger-404@example.com", UserRole.MEMBER
        )

        response = await client.post(
            f"/api/v1/targets/{uuid.uuid4()}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


def test_trigger_scan_inactive_target_returns_404(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_dast_enabled(monkeypatch, enabled=True)

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-trigger-inactive@example.com", UserRole.MEMBER
        )
        target = await _seed_target(
            sessionmaker, "trigger-inactive-target", f"https://{uuid.uuid4()}.test",
            is_active=False,
        )

        response = await client.post(
            f"/api/v1/targets/{target.id}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


def test_trigger_scan_dast_enabled_creates_run_and_task(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `dast_enabled=true`, the HTTP layer reaches `trigger_scan` and
    persists real `ScanRun`/`ScanTask` rows — verified via a direct DB query,
    not just the HTTP response shape. No ZAP container runs here (that live
    proof already exists in `test_process_scan_task_dast_live.py`); this test
    only proves the router correctly wires trigger + enqueue + persistence,
    mirroring `test_scans_api.py::test_trigger_scan_creates_run_returns_202_and_enqueues`.
    """
    _set_dast_enabled(monkeypatch, enabled=True)
    spy = _DelaySpy()
    target_id_holder: dict[str, uuid.UUID] = {}

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-trigger-enabled@example.com", UserRole.MEMBER
        )
        target = await _seed_target(
            sessionmaker, "trigger-enabled-target", f"https://{uuid.uuid4()}.test"
        )
        target_id_holder["id"] = target.id

        response = await client.post(
            f"/api/v1/targets/{target.id}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 202
        body = response.json()
        assert body["scan_target_id"] == str(target.id)
        assert body["repository_id"] is None
        assert body["commit_sha"] is None
        assert body["ref"] is None
        assert body["status"] == "pending"
        assert body["trigger"] == "manual"

        run_id = uuid.UUID(body["id"])
        async with sessionmaker() as session:
            run = await SqlAlchemyScanRunRepository(session).get_by_id(run_id)
            assert run is not None
            assert run.scan_target_id == target.id
            assert run.repository_id is None

            tasks = await SqlAlchemyScanTaskRepository(session).list_by_scan_run(run_id)
            assert len(tasks) == 1
            assert tasks[0].scanner_type == ScannerType.DAST
            assert tasks[0].status == ScanTaskStatus.PENDING

        assert len(spy.calls) == 1

    try:
        asyncio.run(_run_with_client(scenario, spy))
    finally:
        engine = create_async_engine(resolve_database_url())
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        if "id" in target_id_holder:
            asyncio.run(_delete_target_cascade(sessionmaker, target_id_holder["id"]))
        asyncio.run(engine.dispose())
