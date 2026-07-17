"""Acceptance tests for `/api/v1/repositories` — full CRUD + RBAC + soft-delete semantics."""

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
                default_branch="main",
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


def _create_payload(owner: str = "acme", name: str = "widgets") -> dict[str, str]:
    return {
        "provider": "github",
        "owner": owner,
        "name": name,
        "clone_url": f"https://github.com/{owner}/{name}.git",
        "default_branch": "main",
    }


# ---------------------------------------------------------------------------
# 401 — no bearer token on every route
# ---------------------------------------------------------------------------


def test_post_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post("/api/v1/repositories", json=_create_payload())

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_list_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get("/api/v1/repositories")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get(f"/api/v1/repositories/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_patch_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.patch(
            f"/api/v1/repositories/{uuid.uuid4()}", json={"clone_url": "https://x.git"}
        )

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_delete_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.delete(f"/api/v1/repositories/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST — register
# ---------------------------------------------------------------------------


def test_post_creates_repository_returns_201(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-post@example.com", UserRole.MEMBER)

        response = await client.post(
            "/api/v1/repositories",
            json=_create_payload(owner="acme-post", name="widgets-post"),
            headers=_auth_header(member),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["owner"] == "acme-post"
        assert body["is_active"] is True
        assert body["credential_ref"] is None

    asyncio.run(_run_with_client(scenario))


def test_post_duplicate_active_identity_returns_409(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-dup@example.com", UserRole.MEMBER)
        await _seed_repository(sessionmaker, "acme-dup", "widgets-dup")

        response = await client.post(
            "/api/v1/repositories",
            json=_create_payload(owner="acme-dup", name="widgets-dup"),
            headers=_auth_header(member),
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_post_duplicate_soft_deleted_identity_returns_409_no_reactivation(
    migrated_schema: None,
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-dup-soft@example.com", UserRole.MEMBER)
        await _seed_repository(sessionmaker, "acme-dup-soft", "widgets-dup-soft", is_active=False)

        response = await client.post(
            "/api/v1/repositories",
            json=_create_payload(owner="acme-dup-soft", name="widgets-dup-soft"),
            headers=_auth_header(member),
        )

        assert response.status_code == 409

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# GET collection — active-only listing
# ---------------------------------------------------------------------------


def test_list_excludes_inactive_repositories(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-list@example.com", UserRole.MEMBER)
        active = await _seed_repository(sessionmaker, "acme-list", "active-repo")
        inactive = await _seed_repository(
            sessionmaker, "acme-list", "inactive-repo", is_active=False
        )

        response = await client.get("/api/v1/repositories", headers=_auth_header(member))

        assert response.status_code == 200
        ids = {item["id"] for item in response.json()}
        assert str(active.id) in ids
        assert str(inactive.id) not in ids

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# GET by id — 404 on missing or inactive
# ---------------------------------------------------------------------------


def test_get_by_id_returns_active_repository(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-get", "widgets-get")

        response = await client.get(f"/api/v1/repositories/{repo.id}", headers=_auth_header(member))

        assert response.status_code == 200
        assert response.json()["id"] == str(repo.id)

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_inactive_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get-404@example.com", UserRole.MEMBER)
        repo = await _seed_repository(
            sessionmaker, "acme-get-404", "widgets-get-404", is_active=False
        )

        response = await client.get(f"/api/v1/repositories/{repo.id}", headers=_auth_header(member))

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_get_by_id_missing_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-get-missing@example.com", UserRole.MEMBER)

        response = await client.get(
            f"/api/v1/repositories/{uuid.uuid4()}", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# PATCH — mutable fields, identity rejected, 404 on inactive
# ---------------------------------------------------------------------------


def test_patch_mutable_field_returns_200(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-patch@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-patch", "widgets-patch")

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"clone_url": "https://github.com/acme-patch/widgets-patch-new.git"},
            headers=_auth_header(member),
        )

        assert response.status_code == 200
        assert response.json()["clone_url"] == "https://github.com/acme-patch/widgets-patch-new.git"

    asyncio.run(_run_with_client(scenario))


def test_patch_identity_field_returns_422(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-patch-422@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-patch-422", "widgets-patch-422")

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"owner": "should-not-be-accepted"},
            headers=_auth_header(member),
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_patch_null_clone_url_returns_422(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-patch-null-clone@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-patch-null-clone", "widgets-patch-null-clone"
        )

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"clone_url": None},
            headers=_auth_header(member),
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_patch_null_default_branch_returns_422(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-patch-null-branch@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-patch-null-branch", "widgets-patch-null-branch"
        )

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"default_branch": None},
            headers=_auth_header(member),
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_patch_null_credential_ref_clears_field(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-patch-null-cred@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-patch-null-cred", "widgets-patch-null-cred"
        )

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"credential_ref": None},
            headers=_auth_header(member),
        )

        assert response.status_code == 200
        assert response.json()["credential_ref"] is None

    asyncio.run(_run_with_client(scenario))


def test_patch_inactive_repository_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-patch-inactive@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(
            sessionmaker, "acme-patch-inactive", "widgets-patch-inactive", is_active=False
        )

        response = await client.patch(
            f"/api/v1/repositories/{repo.id}",
            json={"clone_url": "https://github.com/acme/ghost.git"},
            headers=_auth_header(member),
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# DELETE — admin-only, idempotent soft-delete
# ---------------------------------------------------------------------------


def test_delete_admin_deactivates_active_repository(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete@example.com", UserRole.ADMIN)
        repo = await _seed_repository(sessionmaker, "acme-delete", "widgets-delete")

        response = await client.delete(
            f"/api/v1/repositories/{repo.id}", headers=_auth_header(admin)
        )

        assert response.status_code == 204

        async with sessionmaker() as session:
            persisted = await SqlAlchemyCodeRepositoryRepository(session).get_by_id(repo.id)
            assert persisted is not None
            assert persisted.is_active is False

    asyncio.run(_run_with_client(scenario))


def test_delete_is_idempotent_on_already_inactive(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete-idem@example.com", UserRole.ADMIN)
        repo = await _seed_repository(
            sessionmaker, "acme-delete-idem", "widgets-delete-idem", is_active=False
        )

        response = await client.delete(
            f"/api/v1/repositories/{repo.id}", headers=_auth_header(admin)
        )

        assert response.status_code == 204

    asyncio.run(_run_with_client(scenario))


def test_delete_missing_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-delete-404@example.com", UserRole.ADMIN)

        response = await client.delete(
            f"/api/v1/repositories/{uuid.uuid4()}", headers=_auth_header(admin)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


def test_delete_member_forbidden_returns_403(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-delete-403@example.com", UserRole.MEMBER)
        repo = await _seed_repository(sessionmaker, "acme-delete-403", "widgets-delete-403")

        response = await client.delete(
            f"/api/v1/repositories/{repo.id}", headers=_auth_header(member)
        )

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))
