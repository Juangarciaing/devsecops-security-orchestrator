"""Acceptance tests for the scan orchestration endpoints:
`POST /api/v1/repositories/{id}/scans`, `GET /api/v1/scans`, `GET /api/v1/scans/{id}`.

Router-level tests monkeypatch `process_scan_task.delay` with a spy — they
prove the router's wiring (use case -> commit -> enqueue) without needing a
live Celery worker or Redis. A SEPARATE end-to-end test proves the full real
pipeline: it triggers a scan over real HTTP, then runs the REAL
`process_scan_task` via `.apply()` (Celery's own synchronous/eager execution
path — the exact mechanism `task_always_eager=True` uses internally, and the
same one `test_process_scan_task.py` already relies on) directly in-process,
then re-polls the API to see the transition. `.apply()` cannot be invoked
from *inside* the async request handler itself: `process_scan_task` calls
`workers.db.run_async`, which does `asyncio.run(...)` internally, and
`asyncio.run()` cannot be nested inside an already-running event loop (the
one driving the HTTP request). Running it at the test's top level (outside
any `asyncio.run(_run_with_client(...))` scenario) sidesteps that conflict
exactly the way a separate worker process would in production.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.api.main import create_app
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import RepositoryProvider, UserRole
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.security.jwt import create_access_token
from orchestrator.infrastructure.security.password_hasher import hash_password

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive timestamp columns


class _DelaySpy:
    """Records `.delay()` calls without touching Redis or running the task."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, scan_task_id: str) -> None:
        self.calls.append(scan_task_id)


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


async def _seed_repository(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
    is_active: bool = True,
    default_branch: str = "main",
) -> CodeRepository:
    async with sessionmaker() as session:
        repository = SqlAlchemyCodeRepositoryRepository(session)
        created = await repository.create(
            CodeRepository(
                id=uuid.uuid4(),
                provider=RepositoryProvider.GITHUB,
                owner=owner,
                name=name,
                clone_url=f"https://github.com/{owner}/{name}.git",
                default_branch=default_branch,
                credential_ref=None,
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


async def _run_with_client(scenario: object, delay_spy: _DelaySpy | None = None) -> None:
    """Build a live-DB-backed app + client, run `scenario(client, sessionmaker)`, tear down.

    When `delay_spy` is given, monkeypatches `process_scan_task.delay`
    directly on the shared Celery task singleton for the duration of the
    scenario, then restores it. `process_scan_task` is imported LAZILY here
    (not at module top level) — same reason `scans.py`'s router imports it
    lazily inside the endpoint: `celery_app.py` resolves `Settings()`
    eagerly at import time, and this fixture runs before `migrated_schema`/
    `db_env` have populated the required env vars via monkeypatch.
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


# ---------------------------------------------------------------------------
# POST /repositories/{id}/scans — 401
# ---------------------------------------------------------------------------


def test_trigger_scan_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post(f"/api/v1/repositories/{uuid.uuid4()}/scans")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST /repositories/{id}/scans — 404 (absent / inactive repository)
# ---------------------------------------------------------------------------


def test_trigger_scan_absent_repository_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-trigger-404@example.com", UserRole.MEMBER)

        response = await client.post(
            f"/api/v1/repositories/{uuid.uuid4()}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


def test_trigger_scan_inactive_repository_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-trigger-inactive@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-trigger-inactive", "widgets-trigger-inactive", is_active=False
        )

        response = await client.post(
            f"/api/v1/repositories/{repo.id}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


# ---------------------------------------------------------------------------
# POST /repositories/{id}/scans — 202 created, enqueues; 200 idempotent, no re-enqueue
# ---------------------------------------------------------------------------


def test_trigger_scan_creates_run_returns_202_and_enqueues(migrated_schema: None) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-trigger@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-trigger", "widgets-trigger")

        response = await client.post(
            f"/api/v1/repositories/{repo.id}/scans",
            json={"commit_sha": "abc123"},
            headers=_auth_header(member),
        )

        assert response.status_code == 202
        body = response.json()
        assert body["repository_id"] == str(repo.id)
        assert body["status"] == "pending"
        assert body["commit_sha"] == "abc123"

        # `.delay()` runs synchronously (D4: commit happens BEFORE enqueue,
        # inside the request handler) — already recorded by the time the
        # response comes back.
        assert len(spy.calls) == 1

    asyncio.run(_run_with_client(scenario, spy))
    assert len(spy.calls) == 1
    uuid.UUID(spy.calls[0])  # a valid scan_task_id was passed


def test_trigger_scan_admin_role_is_also_allowed(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-trigger@example.com", UserRole.ADMIN)
        repo = await _seed_repository(sessionmaker, "acme-trigger-admin", "widgets-trigger-admin")

        response = await client.post(
            f"/api/v1/repositories/{repo.id}/scans", headers=_auth_header(admin)
        )

        assert response.status_code == 202

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


def test_trigger_scan_missing_commit_sha_defaults_to_default_branch(
    migrated_schema: None,
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-trigger-default-branch@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker,
            "acme-trigger-default",
            "widgets-trigger-default",
            default_branch="develop",
        )

        response = await client.post(
            f"/api/v1/repositories/{repo.id}/scans", headers=_auth_header(member)
        )

        assert response.status_code == 202
        assert response.json()["commit_sha"] == "develop"

    asyncio.run(_run_with_client(scenario, _DelaySpy()))


def test_trigger_scan_idempotent_retrigger_returns_200_and_does_not_reenqueue(
    migrated_schema: None,
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-trigger-idem@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-trigger-idem", "widgets-trigger-idem")

        first = await client.post(
            f"/api/v1/repositories/{repo.id}/scans",
            json={"commit_sha": "deadbeef"},
            headers=_auth_header(member),
        )
        assert first.status_code == 202
        first_run_id = first.json()["id"]

        second = await client.post(
            f"/api/v1/repositories/{repo.id}/scans",
            json={"commit_sha": "deadbeef"},
            headers=_auth_header(member),
        )
        assert second.status_code == 200
        assert second.json()["id"] == first_run_id

    asyncio.run(_run_with_client(scenario, spy))
    assert len(spy.calls) == 1  # only the first trigger enqueued


# ---------------------------------------------------------------------------
# GET /scans — paginated list
# ---------------------------------------------------------------------------


def test_list_scans_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get("/api/v1/scans")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_list_scans_returns_paginated_results(migrated_schema: None) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-list-scans@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-list-scans", "widgets-list-scans")

        for commit in ("c1", "c2", "c3"):
            response = await client.post(
                f"/api/v1/repositories/{repo.id}/scans",
                json={"commit_sha": commit},
                headers=_auth_header(member),
            )
            assert response.status_code == 202

        first_page = await client.get(
            "/api/v1/scans", params={"limit": 2, "offset": 0}, headers=_auth_header(member)
        )
        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body) == 2

        second_page = await client.get(
            "/api/v1/scans", params={"limit": 2, "offset": 2}, headers=_auth_header(member)
        )
        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body) == 1

        all_ids = {item["id"] for item in first_body} | {item["id"] for item in second_body}
        assert len(all_ids) == 3

    asyncio.run(_run_with_client(scenario, spy))


# ---------------------------------------------------------------------------
# GET /scans/{id} — status + findings count, 404
# ---------------------------------------------------------------------------


def test_get_scan_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get(f"/api/v1/scans/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_get_scan_unknown_id_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get-scan-404@example.com", UserRole.MEMBER)

        response = await client.get(f"/api/v1/scans/{uuid.uuid4()}", headers=_auth_header(member))

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_get_scan_immediately_after_trigger_shows_pending_with_zero_findings(
    migrated_schema: None,
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-get-scan-pending@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-get-scan-pending", "widgets-get-scan-pending"
        )

        trigger = await client.post(
            f"/api/v1/repositories/{repo.id}/scans", headers=_auth_header(member)
        )
        run_id = trigger.json()["id"]

        detail = await client.get(f"/api/v1/scans/{run_id}", headers=_auth_header(member))

        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "pending"
        assert body["task_status"] == "pending"
        assert body["findings_count"] == 0

    asyncio.run(_run_with_client(scenario, spy))


# ---------------------------------------------------------------------------
# End-to-end: real Celery task execution via the API (no mocked task internals)
# ---------------------------------------------------------------------------


def test_trigger_scan_then_process_scan_task_then_get_shows_completed_with_one_finding(
    migrated_schema: None,
) -> None:
    """Full pipeline: HTTP trigger -> real `process_scan_task.apply()` -> HTTP GET.

    `.delay()` is swapped for a spy (never reaches Redis); the task itself
    runs for REAL via `.apply()` — the exact mechanism `task_always_eager`
    uses internally — proving the DB state machine end-to-end without a live
    broker/worker process. See module docstring for why `.apply()` must run
    outside the request's own event loop.
    """
    from orchestrator.workers.tasks.process_scan import process_scan_task

    spy = _DelaySpy()
    captured: dict[str, str] = {}

    async def trigger_scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-e2e-scan@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-e2e-scan", "widgets-e2e-scan")

        trigger = await client.post(
            f"/api/v1/repositories/{repo.id}/scans", headers=_auth_header(member)
        )
        assert trigger.status_code == 202
        captured["run_id"] = trigger.json()["id"]
        captured["member_email"] = "member-e2e-scan@example.com"

    asyncio.run(_run_with_client(trigger_scenario, spy))

    assert len(spy.calls) == 1
    scan_task_id = spy.calls[0]

    # Run the REAL task synchronously, outside any event loop (mirrors a
    # worker process picking the message off the queue) — exactly the
    # pattern `test_process_scan_task.py` already uses.
    result = process_scan_task.apply(args=(scan_task_id,))
    result.get()

    async def verify_scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-e2e-scan-verify@example.com", UserRole.MEMBER
        )
        detail = await client.get(
            f"/api/v1/scans/{captured['run_id']}", headers=_auth_header(member)
        )

        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "completed"
        assert body["task_status"] == "completed"
        assert body["findings_count"] == 1

    asyncio.run(_run_with_client(verify_scenario))
