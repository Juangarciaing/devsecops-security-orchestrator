"""Integration proof that PR4's sweep composes correctly with PR2's
exclusive `claim_due`/owner-CAS mechanics (github-checks-publisher PR4,
design: "Dispatch and lease"). No delivery call exists yet (PR4->PR5
boundary) — this reuses PR2's repository rather than reimplementing claiming
logic, and only proves claim/lease/reclaim end to end against live Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

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
            claimed_count = await _claim_due_publications(
                session, "worker-a", _NOW + GITHUB_CHECKS_LEASE_DURATION
            )
        # Due predicate composes unchanged: PENDING + expired-lease CLAIMED
        # are both claimed by this one sweep.
        assert claimed_count == 2

        async with sessionmaker() as session:
            # Exclusivity: immediately after, nothing is left due — "worker-a"
            # now holds both rows under a live lease.
            claimed_again = await _claim_due_publications(
                session, "worker-b", _NOW + GITHUB_CHECKS_LEASE_DURATION
            )
        assert claimed_again == 0

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
