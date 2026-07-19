"""Acceptance tests for `POST /api/v1/webhooks/github` — the full rejection
matrix from `sdd/module-10-webhook-handling/design`.

`test_rejected_signature_audit_row_persists_despite_no_raise` is the
DEDICATED D4 test: it proves the design's central claim that returning (not
raising) on an invalid signature lets `get_db_session`'s trailing commit
persist the `signature_valid=false` audit row, by querying the row directly
from the database rather than trusting only the HTTP response.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.api.main import create_app
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider, WebhookOutcome
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.webhook_delivery import WebhookDeliveryModel
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive timestamp columns
_WEBHOOK_URL = "/api/v1/webhooks/github"
_SECRET = "test-webhook-secret"


class _DelaySpy:
    """Records `.delay()` calls without touching Redis or running the task."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, scan_task_id: str) -> None:
        self.calls.append(scan_task_id)


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


def _push_body(owner: str, name: str, ref: str = "refs/heads/main", **overrides: object) -> bytes:
    payload: dict[object, object] = {
        "ref": ref,
        "after": "d" * 40,
        "repository": {"full_name": f"{owner}/{name}"},
        "head_commit": {"id": "e" * 40},
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _headers(
    body: bytes,
    *,
    secret: str | None = _SECRET,
    event: str = "push",
    delivery_id: str | None = None,
) -> dict[str, str]:
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if delivery_id is not None:
        headers["X-GitHub-Delivery"] = delivery_id
    if secret is not None:
        headers["X-Hub-Signature-256"] = _signature(secret, body)
    return headers


async def _run_with_client(
    scenario: object,
    delay_spy: _DelaySpy | None = None,
    *,
    secret_env: str | None = _SECRET,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> None:
    """Build a live-DB-backed app + client, run `scenario(client, sessionmaker)`, tear down.

    Mirrors `test_scans_api.py::_run_with_client`. `monkeypatch` sets
    `GITHUB_WEBHOOK_SECRET` for the duration of the app build so
    `verify_webhook_signature`'s `get_settings()` call resolves the intended
    value; the outer test's `monkeypatch` fixture reverts it on teardown.
    """
    if monkeypatch is not None:
        if secret_env is None:
            monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
        else:
            monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret_env)
        from orchestrator.infrastructure.config.settings import get_settings

        get_settings.cache_clear()

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
# D4 — dedicated audit-survival test
# ---------------------------------------------------------------------------


def test_rejected_signature_audit_row_persists_despite_no_raise(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        body = _push_body("acme-d4", "widgets-d4")
        # Tampered: sign with the WRONG secret so the header is well-formed
        # but the digest never matches.
        headers = _headers(body, secret="wrong-secret", delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"

        # Direct DB query — NOT just trusting the HTTP response — proves the
        # `JSONResponse`-return (not raise) path let `get_db_session`'s
        # trailing commit persist the row instead of rolling it back.
        async with sessionmaker() as session:
            result = await session.execute(
                select(WebhookDeliveryModel).where(WebhookDeliveryModel.signature_valid.is_(False))
            )
            rows = result.scalars().all()

        assert len(rows) == 1
        assert rows[0].outcome == WebhookOutcome.REJECTED_SIGNATURE
        assert rows[0].signature_valid is False
        # Rejected-signature rows never carry the real header value (design:
        # pre-idempotency-checkpoint, avoids a future UNIQUE collision).
        assert rows[0].delivery_id is None

    asyncio.run(_run_with_client(scenario, monkeypatch=monkeypatch))


# ---------------------------------------------------------------------------
# Unset secret — always 401, fail-closed (D1)
# ---------------------------------------------------------------------------


def test_unset_secret_always_returns_401(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        body = _push_body("acme-unset", "widgets-unset")
        headers = _headers(body, secret=_SECRET, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 401

    asyncio.run(_run_with_client(scenario, secret_env=None, monkeypatch=monkeypatch))


# ---------------------------------------------------------------------------
# Non-2xx-never matrix — every non-signature-rejection path returns 200
# ---------------------------------------------------------------------------


def test_non_push_event_returns_200(migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        body = _push_body("acme-ping", "widgets-ping")
        headers = _headers(body, event="ping", delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "ignored_event"

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert spy.calls == []


def test_replayed_delivery_returns_200_and_does_not_create_second_scan_run(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = await _seed_repository(sessionmaker, "acme-replay", "widgets-replay")
        body = _push_body("acme-replay", "widgets-replay")
        delivery_id = str(uuid.uuid4())
        headers = _headers(body, delivery_id=delivery_id)

        first = await client.post(_WEBHOOK_URL, content=body, headers=headers)
        assert first.status_code == 200
        assert first.json()["outcome"] == "accepted"

        second = await client.post(_WEBHOOK_URL, content=body, headers=headers)
        assert second.status_code == 200
        assert second.json()["outcome"] == "duplicate"

        from orchestrator.infrastructure.db.repositories.scan_run_repository import (
            SqlAlchemyScanRunRepository,
        )

        async with sessionmaker() as session:
            runs = await SqlAlchemyScanRunRepository(session).list_by_repository(repo.id)

        assert len(runs) == 1

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert len(spy.calls) == 1


def test_non_default_branch_returns_200_and_no_scan(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = await _seed_repository(
            sessionmaker, "acme-branch", "widgets-branch", default_branch="main"
        )
        body = _push_body("acme-branch", "widgets-branch", ref="refs/heads/feature-x")
        headers = _headers(body, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "ignored_non_default_branch"

        from orchestrator.infrastructure.db.repositories.scan_run_repository import (
            SqlAlchemyScanRunRepository,
        )

        async with sessionmaker() as session:
            runs = await SqlAlchemyScanRunRepository(session).list_by_repository(repo.id)

        assert runs == []

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert spy.calls == []


def test_unregistered_repository_returns_200(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        body = _push_body("nobody", "unregistered")
        headers = _headers(body, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "ignored_unknown_repo"

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert spy.calls == []


def test_inactive_repository_returns_200(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_repository(sessionmaker, "acme-inactive", "widgets-inactive", is_active=False)
        body = _push_body("acme-inactive", "widgets-inactive")
        headers = _headers(body, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "ignored_inactive_repo"

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert spy.calls == []


def test_malformed_payload_returns_200_never_500(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, _sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        body = b"this is not valid json at all {"
        headers = _headers(body, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "invalid_payload"

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert spy.calls == []


# ---------------------------------------------------------------------------
# Valid push — 200, ScanRun(trigger="webhook") created and enqueued
# ---------------------------------------------------------------------------


def test_valid_push_default_branch_returns_200_creates_scan_run_and_enqueues(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _DelaySpy()

    async def scenario(
        client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = await _seed_repository(sessionmaker, "acme-valid", "widgets-valid")
        body = _push_body("acme-valid", "widgets-valid")
        headers = _headers(body, delivery_id=str(uuid.uuid4()))

        response = await client.post(_WEBHOOK_URL, content=body, headers=headers)

        assert response.status_code == 200
        assert response.json()["outcome"] == "accepted"

        from orchestrator.infrastructure.db.repositories.scan_run_repository import (
            SqlAlchemyScanRunRepository,
        )

        async with sessionmaker() as session:
            runs = await SqlAlchemyScanRunRepository(session).list_by_repository(repo.id)

        assert len(runs) == 1
        assert runs[0].trigger == "webhook"
        assert runs[0].commit_sha == "d" * 40

    asyncio.run(_run_with_client(scenario, spy, monkeypatch=monkeypatch))
    assert len(spy.calls) == 1
    uuid.UUID(spy.calls[0])  # a valid scan_task_id was passed
