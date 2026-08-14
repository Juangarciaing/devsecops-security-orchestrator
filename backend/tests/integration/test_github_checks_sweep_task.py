"""Integration proof that PR4's sweep composes correctly with PR2's
exclusive `claim_due`/owner-CAS mechanics (github-checks-publisher PR4,
design: "Dispatch and lease"). No delivery call exists yet (PR4->PR5
boundary) — this reuses PR2's repository rather than reimplementing claiming
logic, and only proves claim/lease/reclaim end to end against live Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.value_objects.enums import (
    GitHubCheckOutcome,
    GitHubCheckPublicationStatus,
    RepositoryProvider,
)
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models import (
    CodeRepositoryModel,
    GitHubCheckPublicationModel,
    ScanRunModel,
)

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC).replace(tzinfo=None)


async def _seed_scan_run(session: AsyncSession) -> uuid.UUID:
    repository = CodeRepositoryModel(
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
    )
    session.add(repository)
    await session.flush()
    scan_run = ScanRunModel(
        repository_id=repository.id, trigger="push", commit_sha="abc123", ref="refs/heads/main"
    )
    session.add(scan_run)
    await session.flush()
    return scan_run.id


async def _seed_publication(
    session: AsyncSession, scan_run_id: uuid.UUID, check_name: str, **overrides: object
) -> uuid.UUID:
    model = GitHubCheckPublicationModel(
        scan_run_id=scan_run_id,
        check_name=check_name,
        outcome=GitHubCheckOutcome.SUCCESS,
        payload_summary="0 findings",
        status=overrides.get("status", GitHubCheckPublicationStatus.PENDING),
        lease_until=overrides.get("lease_until"),
        leased_by=overrides.get("leased_by"),
    )
    session.add(model)
    await session.flush()
    return model.id


async def _sweep_lifecycle() -> None:
    """Exclusive claim + expired-lease reclaim, driven through the sweep's
    OWN `_claim_due_publications` helper — proving composition, not
    re-testing PR2's row-locking. Imported lazily here (after
    `migrated_schema` sets env vars) mirroring `test_process_scan_task.py`'s
    precedent, since `github_checks` transitively resolves `Settings` at
    import time."""
    from orchestrator.workers.tasks.github_checks import (
        GITHUB_CHECKS_LEASE_DURATION,
        _claim_due_publications,
    )

    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_id = await _seed_scan_run(session)
            pending_id = await _seed_publication(session, scan_run_id, "pending")
            # Task 4.1's "completion worker dying before wakeup": a prior
            # sweep already claimed this row, but the delivery worker that
            # should have called `mark_delivered`/`release` never ran —
            # its lease is now in the past.
            dead_worker_id = await _seed_publication(
                session,
                scan_run_id,
                "claimed-by-dead-worker",
                status=GitHubCheckPublicationStatus.CLAIMED,
                lease_until=_NOW - GITHUB_CHECKS_LEASE_DURATION,
                leased_by="worker-that-died-before-wakeup",
            )
            await session.commit()

        async with sessionmaker() as session:
            claimed = await _claim_due_publications(
                session, "worker-a", _NOW + GITHUB_CHECKS_LEASE_DURATION
            )
        # Due predicate composes unchanged: PENDING + expired-lease CLAIMED
        # are both claimed by this one sweep.
        assert len(claimed) == 2

        async with sessionmaker() as session:
            # Exclusivity: immediately after, nothing is left due — "worker-a"
            # now holds both rows under a live lease.
            claimed_again = await _claim_due_publications(
                session, "worker-b", _NOW + GITHUB_CHECKS_LEASE_DURATION
            )
        assert claimed_again == []

        async with sessionmaker() as session:
            pending_model = await session.get(GitHubCheckPublicationModel, pending_id)
            dead_worker_model = await session.get(GitHubCheckPublicationModel, dead_worker_id)
            assert pending_model is not None
            assert pending_model.status == GitHubCheckPublicationStatus.CLAIMED
            assert pending_model.leased_by == "worker-a"
            # The dead worker's stale claim is reclaimed by the next sweep —
            # PR2's expired-lease reclaim + this PR's sweep compose end to end.
            assert dead_worker_model is not None
            assert dead_worker_model.status == GitHubCheckPublicationStatus.CLAIMED
            assert dead_worker_model.leased_by == "worker-a"
            assert dead_worker_model.lease_until is not None
            assert dead_worker_model.lease_until > _NOW
    finally:
        await engine.dispose()


def test_sweep_claims_due_rows_exclusively_and_reclaims_a_dead_workers_expired_lease(
    migrated_schema: None,
) -> None:
    asyncio.run(_sweep_lifecycle())


def _generate_test_rsa_private_key(tmp_path: Path) -> Path:
    """Throwaway local RSA keypair — NEVER a real GitHub App key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "test-app.pem"
    key_path.write_bytes(pem)
    return key_path


def _delivery_settings(key_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        github_checks_delivery_enabled=True,
        github_app_id="1",
        github_app_private_key_file=str(key_path),
    )


async def _run_sweep_against(
    key_path: Path, handler: Callable[[httpx.Request], httpx.Response]
) -> GitHubCheckPublicationModel:
    """Seed one PENDING publication, run `_run_sweep` against a mocked GitHub
    API (never real), and return the persisted row afterward."""
    from orchestrator.workers.tasks.github_checks import _run_sweep

    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_id = await _seed_scan_run(session)
            publication_id = await _seed_publication(session, scan_run_id, "check")
            await session.commit()

        settings = _delivery_settings(key_path)
        async with sessionmaker() as session:
            claimed = await _run_sweep(
                session,
                settings,
                "worker-a",
                _NOW + timedelta(minutes=5),
                http_client_factory=lambda: httpx.AsyncClient(
                    base_url="https://api.github.com", transport=httpx.MockTransport(handler)
                ),
            )
        assert claimed == 1

        async with sessionmaker() as session:
            model = await session.get(GitHubCheckPublicationModel, publication_id)
            assert model is not None
            return model
    finally:
        await engine.dispose()


_EXPIRES_AT = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _handler_for(
    status_after_lookup: int, check_run_response_id: int = 555
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/installation"):
            return httpx.Response(200, json={"id": 42})
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_fake", "expires_at": _EXPIRES_AT})
        if request.url.path.endswith("/check-runs") and request.method == "GET":
            return httpx.Response(200, json={"check_runs": []})
        if status_after_lookup == 201:
            return httpx.Response(201, json={"id": check_run_response_id})
        return httpx.Response(status_after_lookup, json={"message": "mocked failure"})

    return handler


def test_sweep_delivers_a_claimed_publication(migrated_schema: None, tmp_path: Path) -> None:
    key_path = _generate_test_rsa_private_key(tmp_path)

    model = asyncio.run(_run_sweep_against(key_path, _handler_for(201)))

    assert model.status == GitHubCheckPublicationStatus.DELIVERED
    assert model.leased_by is None
    assert model.lease_until is None


def test_sweep_reschedules_a_retryable_delivery_failure(
    migrated_schema: None, tmp_path: Path
) -> None:
    key_path = _generate_test_rsa_private_key(tmp_path)

    model = asyncio.run(_run_sweep_against(key_path, _handler_for(500)))

    assert model.status == GitHubCheckPublicationStatus.CLAIMED
    assert model.leased_by == "worker-a"
    assert model.attempt_count == 1
    assert model.lease_until is not None
    assert model.lease_until > _NOW


def test_sweep_dead_letters_a_terminal_delivery_failure(
    migrated_schema: None, tmp_path: Path
) -> None:
    key_path = _generate_test_rsa_private_key(tmp_path)

    model = asyncio.run(_run_sweep_against(key_path, _handler_for(422)))

    assert model.status == GitHubCheckPublicationStatus.DEAD
    assert model.dead_letter_reason == "http_422"
    assert model.attempt_count == 1
    assert model.leased_by is None


async def _run_sweep_after_a_simulated_worker_crash(
    key_path: Path, handler: Callable[[httpx.Request], httpx.Response]
) -> GitHubCheckPublicationModel:
    """Task 7.3's runtime proof: seed a row already `CLAIMED` by a worker
    whose lease has since expired — simulating a worker process that claimed
    the row and was killed/restarted BEFORE it ever attempted delivery (the
    same "dead-worker-before-wakeup" shape `_sweep_lifecycle` above proves
    for claim/reclaim alone) — then run one independent `_run_sweep`
    invocation (a later sweep cycle, different owner) and confirm it
    reclaims AND delivers the row rather than losing it.

    Live Postgres/Redis/kind ARE already running locally in this session
    (per PR6c's own notes), but driving a real `docker compose kill -s
    SIGKILL worker` mid-HTTP-call against a live Celery process from inside
    a single pytest run is impractical and non-deterministic here. Expired-
    lease reclaim is the exact, deterministic mechanism production recovery
    actually relies on (`GITHUB_CHECKS_LEASE_DURATION`'s own docstring: "a
    delivery worker dying mid-flight only strands its claimed rows for a few
    sweep cycles, not indefinitely") — this proves that mechanism composes
    with a REAL delivery call end to end, not just with claim alone as
    `_sweep_lifecycle` already does. The intended production verification
    procedure — seeding this same row shape against a live `docker compose`
    stack, `docker compose kill -s SIGKILL worker` mid-delivery, and
    confirming the next Beat-triggered sweep cycle redelivers it — is
    documented, not executed, in this session (see README "GitHub Checks
    publishing").
    """
    from orchestrator.workers.tasks.github_checks import GITHUB_CHECKS_LEASE_DURATION, _run_sweep

    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_id = await _seed_scan_run(session)
            publication_id = await _seed_publication(
                session,
                scan_run_id,
                "crashed-mid-flight",
                status=GitHubCheckPublicationStatus.CLAIMED,
                lease_until=_NOW - GITHUB_CHECKS_LEASE_DURATION,
                leased_by="worker-that-was-killed-before-delivering",
            )
            await session.commit()

        settings = _delivery_settings(key_path)
        # The next sweep cycle after the simulated crash: reclaims the stale
        # lease AND delivers within the same invocation (`_run_sweep`'s real
        # shape — never a separate claim-only step in production).
        async with sessionmaker() as session:
            claimed = await _run_sweep(
                session,
                settings,
                "worker-b",
                _NOW + timedelta(minutes=5),
                http_client_factory=lambda: httpx.AsyncClient(
                    base_url="https://api.github.com", transport=httpx.MockTransport(handler)
                ),
            )
        assert claimed == 1

        async with sessionmaker() as session:
            model = await session.get(GitHubCheckPublicationModel, publication_id)
            assert model is not None
            return model
    finally:
        await engine.dispose()


def test_sweep_recovers_and_delivers_a_publication_abandoned_by_a_crashed_worker(
    migrated_schema: None, tmp_path: Path
) -> None:
    key_path = _generate_test_rsa_private_key(tmp_path)

    model = asyncio.run(
        _run_sweep_after_a_simulated_worker_crash(key_path, _handler_for(201))
    )

    assert model.status == GitHubCheckPublicationStatus.DELIVERED
    assert model.leased_by is None
    assert model.lease_until is None
