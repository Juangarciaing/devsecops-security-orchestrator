"""Acceptance tests for `/api/v1/findings*`:
`GET /findings`, `GET /findings/{id}`, `POST /findings/{id}/suppress`,
`POST /findings/{id}/unsuppress`.

Seeds `Finding` rows directly through `SqlAlchemyFindingRepository.create`
(no HTTP write path exists for findings — Module 8 non-goal), mirroring the
seed-helper convention already established in `test_finding_repository.py`
and `test_scans_api.py`.
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
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
    UserRole,
)
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
    sessionmaker: async_sessionmaker[AsyncSession], owner: str, name: str
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
        await session.commit()
        return created


async def _seed_scan_run_and_task(
    sessionmaker: async_sessionmaker[AsyncSession], repository_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as session:
        scan_run_repo = SqlAlchemyScanRunRepository(session)
        run = await scan_run_repo.create(
            ScanRun(
                id=uuid.uuid4(),
                repository_id=repository_id,
                status=ScanRunStatus.COMPLETED,
                trigger="manual",
                commit_sha="abc123",
                ref="abc123",
                created_at=_NOW,
                started_at=_NOW,
                completed_at=_NOW,
            )
        )
        await session.commit()
        run_id = run.id

    async with sessionmaker() as session:
        scan_task_repo = SqlAlchemyScanTaskRepository(session)
        task = await scan_task_repo.create(
            ScanTask(
                id=uuid.uuid4(),
                scan_run_id=run_id,
                scanner_type=ScannerType.SECRETS,
                status=ScanTaskStatus.COMPLETED,
                started_at=_NOW,
                completed_at=_NOW,
                error_message=None,
            )
        )
        await session.commit()
        task_id = task.id

    return run_id, task_id


async def _seed_finding(
    sessionmaker: async_sessionmaker[AsyncSession],
    scan_task_id: uuid.UUID,
    repository_id: uuid.UUID,
    last_seen_scan_run_id: uuid.UUID,
    **overrides: object,
) -> Finding:
    async with sessionmaker() as session:
        finding_repo = SqlAlchemyFindingRepository(session)
        defaults: dict[str, object] = {
            "id": uuid.uuid4(),
            "scan_task_id": scan_task_id,
            "severity": FindingSeverity.HIGH,
            "status": FindingStatus.OPEN,
            "rule_id": "generic-api-key",
            "title": "Hardcoded API key",
            "fingerprint": f"fp-{uuid.uuid4()}",
            "created_at": _NOW,
            "updated_at": _NOW,
            "repository_id": repository_id,
            "first_seen_scan_run_id": last_seen_scan_run_id,
            "last_seen_scan_run_id": last_seen_scan_run_id,
            "raw_evidence": {"match": "sk_live_abc123"},
            "snippet": "API_KEY='sk_live_abc123'",
            "file_path": "src/config.py",
            "line_number": 4,
        }
        defaults.update(overrides)
        created = await finding_repo.create(Finding(**defaults))  # type: ignore[arg-type]
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


async def _seed_one_finding(
    sessionmaker: async_sessionmaker[AsyncSession], owner: str, name: str, **overrides: object
) -> Finding:
    repo = await _seed_repository(sessionmaker, owner, name)
    run_id, task_id = await _seed_scan_run_and_task(sessionmaker, repo.id)
    return await _seed_finding(sessionmaker, task_id, repo.id, run_id, **overrides)


# ---------------------------------------------------------------------------
# GET /findings — cross-run list + filters
# ---------------------------------------------------------------------------


def test_list_findings_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get("/api/v1/findings")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_list_findings_no_filters_empty_result_returns_200(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-list-findings-empty@example.com", UserRole.MEMBER
        )

        response = await client.get("/api/v1/findings", headers=_auth_header(member))

        assert response.status_code == 200
        assert response.json() == []

    asyncio.run(_run_with_client(scenario))


def test_list_findings_invalid_severity_enum_returns_422(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-list-findings-422@example.com", UserRole.MEMBER
        )

        response = await client.get(
            "/api/v1/findings", params={"severity": "not-a-severity"}, headers=_auth_header(member)
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_list_findings_combined_filters_return_only_matching(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-list-findings-combined@example.com", UserRole.MEMBER
        )
        repo = await _seed_repository(sessionmaker, "acme-combined", "widgets-combined")
        run_id, secrets_task_id = await _seed_scan_run_and_task(sessionmaker, repo.id)

        async with sessionmaker() as session:
            scan_task_repo = SqlAlchemyScanTaskRepository(session)
            sast_task = await scan_task_repo.create(
                ScanTask(
                    id=uuid.uuid4(),
                    scan_run_id=run_id,
                    scanner_type=ScannerType.SAST,
                    status=ScanTaskStatus.COMPLETED,
                    started_at=_NOW,
                    completed_at=_NOW,
                    error_message=None,
                )
            )
            await session.commit()

        matching = await _seed_finding(
            sessionmaker,
            secrets_task_id,
            repo.id,
            run_id,
            severity=FindingSeverity.HIGH,
            status=FindingStatus.OPEN,
        )
        # wrong severity
        await _seed_finding(
            sessionmaker,
            secrets_task_id,
            repo.id,
            run_id,
            severity=FindingSeverity.LOW,
            status=FindingStatus.OPEN,
        )
        # wrong status
        await _seed_finding(
            sessionmaker,
            secrets_task_id,
            repo.id,
            run_id,
            severity=FindingSeverity.HIGH,
            status=FindingStatus.RESOLVED,
        )
        # wrong scanner_type
        await _seed_finding(
            sessionmaker,
            sast_task.id,
            repo.id,
            run_id,
            severity=FindingSeverity.HIGH,
            status=FindingStatus.OPEN,
        )

        response = await client.get(
            "/api/v1/findings",
            params={
                "severity": "high",
                "status": "open",
                "repository_id": str(repo.id),
                "scanner_type": "secrets",
            },
            headers=_auth_header(member),
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(matching.id)

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# GET /findings/{id} — detail + redaction
# ---------------------------------------------------------------------------


def test_get_finding_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.get(f"/api/v1/findings/{uuid.uuid4()}")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_get_finding_unknown_id_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-get-finding-404@example.com", UserRole.MEMBER
        )

        response = await client.get(
            f"/api/v1/findings/{uuid.uuid4()}", headers=_auth_header(member)
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


def test_get_finding_member_sees_masked_secret_admin_sees_real_value(
    migrated_schema: None,
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-redaction@example.com", UserRole.MEMBER)
        admin = await _seed_user(sessionmaker, "admin-redaction@example.com", UserRole.ADMIN)
        finding = await _seed_one_finding(sessionmaker, "acme-redaction", "widgets-redaction")

        member_response = await client.get(
            f"/api/v1/findings/{finding.id}", headers=_auth_header(member)
        )
        admin_response = await client.get(
            f"/api/v1/findings/{finding.id}", headers=_auth_header(admin)
        )

        assert member_response.status_code == 200
        member_body = member_response.json()
        assert member_body["raw_evidence"] is None
        assert member_body["snippet"] is None
        assert member_body["file_path"] is None
        assert member_body["line_number"] is None
        assert member_body["severity"] == "high"
        assert member_body["status"] == "open"
        assert member_body["rule_id"] == finding.rule_id
        assert member_body["fingerprint"] == finding.fingerprint

        assert admin_response.status_code == 200
        admin_body = admin_response.json()
        assert admin_body["raw_evidence"] == finding.raw_evidence
        assert admin_body["snippet"] == finding.snippet
        assert admin_body["file_path"] == finding.file_path
        assert admin_body["line_number"] == finding.line_number

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST /findings/{id}/suppress
# ---------------------------------------------------------------------------


def test_suppress_finding_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post(f"/api/v1/findings/{uuid.uuid4()}/suppress")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_suppress_finding_unknown_id_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-suppress-404@example.com", UserRole.MEMBER)

        response = await client.post(
            f"/api/v1/findings/{uuid.uuid4()}/suppress", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


def test_suppress_open_finding_transitions_and_advances_updated_at(
    migrated_schema: None,
) -> None:
    """Live round-trip: proves `update_status`'s `MissingGreenlet` fix holds
    through the real ORM path AND that `updated_at` genuinely advances."""

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(sessionmaker, "member-suppress-open@example.com", UserRole.MEMBER)
        finding = await _seed_one_finding(
            sessionmaker, "acme-suppress-open", "widgets-suppress-open", status=FindingStatus.OPEN
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/suppress", headers=_auth_header(member)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "suppressed"
        assert datetime.fromisoformat(body["updated_at"]) > finding.updated_at

    asyncio.run(_run_with_client(scenario))


def test_suppress_already_suppressed_finding_is_idempotent_no_op(
    migrated_schema: None,
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-suppress-idem@example.com", UserRole.ADMIN)
        finding = await _seed_one_finding(
            sessionmaker,
            "acme-suppress-idem",
            "widgets-suppress-idem",
            status=FindingStatus.SUPPRESSED,
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/suppress", headers=_auth_header(admin)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "suppressed"
        assert datetime.fromisoformat(body["updated_at"]) == finding.updated_at

    asyncio.run(_run_with_client(scenario))


def test_suppress_resolved_finding_returns_409(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-suppress-illegal@example.com", UserRole.MEMBER
        )
        finding = await _seed_one_finding(
            sessionmaker,
            "acme-suppress-illegal",
            "widgets-suppress-illegal",
            status=FindingStatus.RESOLVED,
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/suppress", headers=_auth_header(member)
        )

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

    asyncio.run(_run_with_client(scenario))


# ---------------------------------------------------------------------------
# POST /findings/{id}/unsuppress — mirrors suppress
# ---------------------------------------------------------------------------


def test_unsuppress_finding_without_token_returns_401(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        response = await client.post(f"/api/v1/findings/{uuid.uuid4()}/unsuppress")

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario))


def test_unsuppress_finding_unknown_id_returns_404(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-unsuppress-404@example.com", UserRole.MEMBER
        )

        response = await client.post(
            f"/api/v1/findings/{uuid.uuid4()}/unsuppress", headers=_auth_header(member)
        )

        assert response.status_code == 404

    asyncio.run(_run_with_client(scenario))


def test_unsuppress_suppressed_finding_transitions_to_open(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-unsuppress-open@example.com", UserRole.MEMBER
        )
        finding = await _seed_one_finding(
            sessionmaker,
            "acme-unsuppress-open",
            "widgets-unsuppress-open",
            status=FindingStatus.SUPPRESSED,
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/unsuppress", headers=_auth_header(member)
        )

        assert response.status_code == 200
        assert response.json()["status"] == "open"

    asyncio.run(_run_with_client(scenario))


def test_unsuppress_already_open_finding_is_idempotent_no_op(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        admin = await _seed_user(sessionmaker, "admin-unsuppress-idem@example.com", UserRole.ADMIN)
        finding = await _seed_one_finding(
            sessionmaker,
            "acme-unsuppress-idem",
            "widgets-unsuppress-idem",
            status=FindingStatus.OPEN,
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/unsuppress", headers=_auth_header(admin)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "open"
        assert datetime.fromisoformat(body["updated_at"]) == finding.updated_at

    asyncio.run(_run_with_client(scenario))


def test_unsuppress_false_positive_finding_returns_409(migrated_schema: None) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        member = await _seed_user(
            sessionmaker, "member-unsuppress-illegal@example.com", UserRole.MEMBER
        )
        finding = await _seed_one_finding(
            sessionmaker,
            "acme-unsuppress-illegal",
            "widgets-unsuppress-illegal",
            status=FindingStatus.FALSE_POSITIVE,
        )

        response = await client.post(
            f"/api/v1/findings/{finding.id}/unsuppress", headers=_auth_header(member)
        )

        assert response.status_code == 409

    asyncio.run(_run_with_client(scenario))
