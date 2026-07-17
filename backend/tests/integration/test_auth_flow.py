"""Integration tests for the `/api/v1/auth` and `/api/v1/users` HTTP flow, against
a live Postgres schema: login, guarded `/me`, admin-only user provisioning,
and API-key issue/list/revoke.

No `pytest-asyncio` plugin in this project (established convention, see
`test_repositories.py`): each test's ENTIRE async body (seed data, HTTP calls,
engine disposal) runs inside a single `asyncio.run(...)` call so every
asyncpg connection is opened and closed on the SAME event loop — mixing
loops (e.g. a separately-`asyncio.run`-seeded engine with `TestClient`'s own
portal loop) breaks asyncpg's connection teardown.

`get_db_session` is overridden (FastAPI `dependency_overrides`) to bind to the
live test engine instead of the process-wide cached one, matching the
`migrated_schema` fixture's schema lifecycle. Requests are made via
`httpx.AsyncClient` + `ASGITransport` (not `TestClient`) so the app runs on
the same event loop as the rest of the test body.
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
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.security.jwt import create_access_token
from orchestrator.infrastructure.security.password_hasher import hash_password

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: `users`/`api_keys` timestamp columns are TZ-naive


async def _seed_user(
    sessionmaker: async_sessionmaker[AsyncSession], email: str, password: str, role: UserRole
) -> User:
    async with sessionmaker() as session:
        repository = SqlAlchemyUserRepository(session)
        created = await repository.create(
            User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await session.commit()
        return created


async def _seed_inactive_user(
    sessionmaker: async_sessionmaker[AsyncSession], email: str, password: str
) -> User:
    async with sessionmaker() as session:
        repository = SqlAlchemyUserRepository(session)
        created = await repository.create(
            User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hash_password(password),
                role=UserRole.MEMBER,
                is_active=False,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await session.commit()
        return created


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _run_with_client(scenario: object) -> None:
    """Build a live-DB-backed app + client, run `scenario(client, sessionmaker)`, tear down."""
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
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client, sessionmaker)  # type: ignore[operator]
    finally:
        await engine.dispose()


def test_login_success_returns_jwt(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        user = await _seed_user(
            sessionmaker, "login-ok@example.com", "correct-horse", UserRole.MEMBER
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "correct-horse"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str) and body["access_token"]

    asyncio.run(_run_with_client(scenario))


def test_login_wrong_password_returns_401_problem_json(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        user = await _seed_user(
            sessionmaker, "login-wrong@example.com", "correct-horse", UserRole.MEMBER
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"}
        )

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_login_unknown_email_returns_401_problem_json(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
        )

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_login_inactive_user_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        user = await _seed_inactive_user(
            sessionmaker, "login-inactive@example.com", "correct-horse"
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "correct-horse"}
        )

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_me_returns_current_user_without_hashed_password(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        user = await _seed_user(
            sessionmaker, "me-user@example.com", "correct-horse", UserRole.MEMBER
        )

        response = await client.get("/api/v1/auth/me", headers=_auth_header(user))

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == user.email
        assert "hashed_password" not in body

    asyncio.run(_run_with_client(scenario))


def test_create_user_as_admin_succeeds_and_duplicate_email_is_rejected(
    migrated_schema: None,
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(
            sessionmaker, "admin-creator@example.com", "adminpass", UserRole.ADMIN
        )

        first = await client.post(
            "/api/v1/users",
            json={"email": "provisioned@example.com", "password": "s3cret-passw0rd"},
            headers=_auth_header(admin),
        )
        assert first.status_code == 201
        assert first.json()["email"] == "provisioned@example.com"

        duplicate = await client.post(
            "/api/v1/users",
            json={"email": "provisioned@example.com", "password": "another-password"},
            headers=_auth_header(admin),
        )
        assert duplicate.status_code == 409
        assert duplicate.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_create_user_as_non_admin_gets_403(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-blocked@example.com", "memberpass", UserRole.MEMBER
        )

        response = await client.post(
            "/api/v1/users",
            json={"email": "should-not-exist@example.com", "password": "s3cret-passw0rd"},
            headers=_auth_header(member),
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_issue_list_and_revoke_api_key(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        user = await _seed_user(
            sessionmaker, "apikey-owner@example.com", "ownerpass", UserRole.MEMBER
        )

        issued = await client.post("/api/v1/auth/api-keys", headers=_auth_header(user))
        assert issued.status_code == 201
        issued_body = issued.json()
        assert issued_body["raw_key"].startswith(issued_body["api_key"]["key_prefix"] + ".")
        key_id = issued_body["api_key"]["id"]

        listed = await client.get("/api/v1/auth/api-keys", headers=_auth_header(user))
        assert listed.status_code == 200
        assert any(key["id"] == key_id and key["is_active"] for key in listed.json())

        revoked = await client.post(
            f"/api/v1/auth/api-keys/{key_id}/revoke", headers=_auth_header(user)
        )
        assert revoked.status_code == 200
        assert revoked.json()["is_active"] is False

    asyncio.run(_run_with_client(scenario))
