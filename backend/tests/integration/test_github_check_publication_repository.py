"""`GitHubCheckPublicationPort` claim/CAS repository behavior against a live
Postgres (spec: Single Logical Check Run — claim exclusivity, owner-CAS
complete/release, expired-lease reclaim).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.value_objects.enums import (
    GitHubCheckOutcome,
    GitHubCheckPublicationStatus,
    RepositoryProvider,
)
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models import (
    CodeRepositoryModel,
    GitHubCheckPublicationModel,
    ScanRunModel,
)
from orchestrator.infrastructure.db.repositories.github_check_publication_repository import (
    SqlAlchemyGitHubCheckPublicationRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC).replace(tzinfo=None)
_LEASE = timedelta(minutes=5)


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


async def _claim_release_lifecycle() -> None:
    """Due predicate + `SKIP LOCKED` exclusivity, expired-lease reclaim,
    and owner-CAS complete/release."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_id = await _seed_scan_run(session)
            pending_id = await _seed_publication(session, scan_run_id, "pending")
            live_id = await _seed_publication(
                session,
                scan_run_id,
                "claimed-live",
                status=GitHubCheckPublicationStatus.CLAIMED,
                lease_until=_NOW + _LEASE,
                leased_by="worker-alive",
            )
            expired_id = await _seed_publication(
                session,
                scan_run_id,
                "claimed-expired",
                status=GitHubCheckPublicationStatus.CLAIMED,
                lease_until=_NOW - _LEASE,
                leased_by="worker-dead",
            )
            delivered_id = await _seed_publication(
                session, scan_run_id, "delivered", status=GitHubCheckPublicationStatus.DELIVERED
            )
            await session.commit()

        # `SKIP LOCKED`: a concurrent claim must skip worker-a's locked rows.
        lock_acquired = asyncio.Event()

        async def _worker_a() -> list[uuid.UUID]:
            async with sessionmaker() as session:
                repo = SqlAlchemyGitHubCheckPublicationRepository(session)
                claimed = await repo.claim_due(limit=10, owner="a", lease_until=_NOW + _LEASE)
                lock_acquired.set()
                await asyncio.sleep(0.3)
                await session.commit()
                return [p.id for p in claimed]

        async def _worker_b() -> list[uuid.UUID]:
            await lock_acquired.wait()
            async with sessionmaker() as session:
                repo = SqlAlchemyGitHubCheckPublicationRepository(session)
                claimed = await repo.claim_due(limit=10, owner="b", lease_until=_NOW + _LEASE)
                await session.commit()
                return [p.id for p in claimed]

        claimed_by_a, claimed_by_b = await asyncio.gather(_worker_a(), _worker_b())

        # Due predicate: PENDING + expired-lease CLAIMED only.
        assert set(claimed_by_a) == {pending_id, expired_id}
        assert claimed_by_b == []
        assert live_id not in claimed_by_a
        assert delivered_id not in claimed_by_a

        async with sessionmaker() as session:
            repo = SqlAlchemyGitHubCheckPublicationRepository(session)
            claimed_model = await session.get(GitHubCheckPublicationModel, pending_id)
            assert claimed_model is not None
            assert claimed_model.status == GitHubCheckPublicationStatus.CLAIMED
            assert claimed_model.leased_by == "a"

            # Owner-CAS: only the true owner can complete/release its claim.
            assert (
                await repo.mark_delivered(
                    pending_id,
                    owner="b",
                    external_id="wrong-owner",
                    check_run_id=1,
                    attempt_count=1,
                )
                is False
            )
            assert await repo.release(expired_id, owner="b") is False
            assert (
                await repo.mark_delivered(
                    pending_id,
                    owner="a",
                    external_id="github-checks:test",
                    check_run_id=42,
                    attempt_count=2,
                )
                is True
            )
            assert await repo.release(expired_id, owner="a") is True
            await session.commit()

        async with sessionmaker() as session:
            delivered_model = await session.get(GitHubCheckPublicationModel, pending_id)
            released_model = await session.get(GitHubCheckPublicationModel, expired_id)
            assert delivered_model is not None
            assert delivered_model.status == GitHubCheckPublicationStatus.DELIVERED
            assert delivered_model.leased_by is None
            # PR5 fix: mark_delivered persists the GitHub-side identity.
            assert delivered_model.external_id == "github-checks:test"
            assert delivered_model.check_run_id == 42
            # attempt_count fix: the TOTAL attempts it took, not whatever an
            # earlier reschedule/mark_dead call happened to leave behind.
            assert delivered_model.attempt_count == 2
            assert released_model is not None
            assert released_model.status == GitHubCheckPublicationStatus.PENDING
            assert released_model.lease_until is None
            assert released_model.leased_by is None
    finally:
        await engine.dispose()


def test_claim_due_skip_locked_and_owner_cas(migrated_schema: None) -> None:
    asyncio.run(_claim_release_lifecycle())


async def _dead_letter_and_replay_lifecycle() -> None:
    """PR6 (design: "Dead-letter + replay"): owner-CAS `reschedule`/
    `mark_dead`, and the explicit, non-owner-scoped `replay` operation."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            scan_run_id = await _seed_scan_run(session)
            claimed_id = await _seed_publication(
                session,
                scan_run_id,
                "claimed",
                status=GitHubCheckPublicationStatus.CLAIMED,
                lease_until=_NOW + _LEASE,
                leased_by="worker-a",
            )
            dead_id = await _seed_publication(
                session, scan_run_id, "dead", status=GitHubCheckPublicationStatus.DEAD
            )
            disabled_id = await _seed_publication(
                session, scan_run_id, "disabled", status=GitHubCheckPublicationStatus.DISABLED
            )
            delivered_id = await _seed_publication(
                session, scan_run_id, "delivered", status=GitHubCheckPublicationStatus.DELIVERED
            )
            await session.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyGitHubCheckPublicationRepository(session)

            # Owner-CAS: only the true owner can reschedule/mark-dead its claim.
            assert (
                await repo.reschedule(
                    claimed_id, owner="wrong", lease_until=_NOW + _LEASE, attempt_count=2
                )
                is False
            )
            assert (
                await repo.reschedule(
                    claimed_id, owner="worker-a", lease_until=_NOW + 2 * _LEASE, attempt_count=2
                )
                is True
            )
            await session.commit()

        async with sessionmaker() as session:
            rescheduled = await session.get(GitHubCheckPublicationModel, claimed_id)
            assert rescheduled is not None
            assert rescheduled.status == GitHubCheckPublicationStatus.CLAIMED
            assert rescheduled.attempt_count == 2
            assert rescheduled.lease_until == _NOW + 2 * _LEASE

            repo = SqlAlchemyGitHubCheckPublicationRepository(session)
            assert (
                await repo.mark_dead(
                    claimed_id, owner="wrong", attempt_count=3, dead_letter_reason="http_422"
                )
                is False
            )
            assert (
                await repo.mark_dead(
                    claimed_id,
                    owner="worker-a",
                    attempt_count=3,
                    dead_letter_reason="attempts_exhausted",
                )
                is True
            )
            await session.commit()

        async with sessionmaker() as session:
            dead_model = await session.get(GitHubCheckPublicationModel, claimed_id)
            assert dead_model is not None
            assert dead_model.status == GitHubCheckPublicationStatus.DEAD
            assert dead_model.attempt_count == 3
            assert dead_model.dead_letter_reason == "attempts_exhausted"
            assert dead_model.leased_by is None
            assert dead_model.lease_until is None

            repo = SqlAlchemyGitHubCheckPublicationRepository(session)
            # `replay` is explicit and NOT owner-scoped; only DISABLED/DEAD
            # rows are eligible — everything else is a no-op.
            assert await repo.replay(delivered_id) is False
            assert await repo.replay(dead_id) is True
            assert await repo.replay(disabled_id) is True
            await session.commit()

        async with sessionmaker() as session:
            replayed_dead = await session.get(GitHubCheckPublicationModel, dead_id)
            replayed_disabled = await session.get(GitHubCheckPublicationModel, disabled_id)
            assert replayed_dead is not None
            assert replayed_dead.status == GitHubCheckPublicationStatus.PENDING
            assert replayed_dead.dead_letter_reason is None
            assert replayed_disabled is not None
            assert replayed_disabled.status == GitHubCheckPublicationStatus.PENDING
            assert replayed_disabled.dead_letter_reason is None
    finally:
        await engine.dispose()


def test_reschedule_mark_dead_and_replay(migrated_schema: None) -> None:
    asyncio.run(_dead_letter_and_replay_lifecycle())
