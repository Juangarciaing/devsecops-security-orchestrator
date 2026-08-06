"""`sweep_github_check_publications_task` — PR4's disabled-by-default lease
sweep for the GitHub Checks outbox (design: "Dispatch and lease").

PR4 -> PR5 boundary: GitHub App auth (JWT, installation tokens) and the
actual HTTP delivery call to `api.github.com` do NOT exist yet — that is
PR5's job. This task only proves PR2's exclusive `claim_due` claim/lease
mechanics compose on a schedule: claim due rows, hold the lease, and let a
later sweep reclaim them if nothing ever completes/releases them. Zero
network I/O, zero GitHub App auth — no delivery call exists here; closing
that gap is PR5's job, not this one's.

`Settings.github_checks_delivery_enabled` (default `False`) gates the
ENTIRE claim step, not just the nonexistent delivery call: disabled means
this task returns before ever calling `claim_due`. Claiming a row with no
deliverer able to complete it would only strand it `CLAIMED` until its
lease expires — wasteful while PR5 has not landed. PR5 flips this same
flag's semantics to also enable the real delivery call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.db.repositories.github_check_publication_repository import (
    SqlAlchemyGitHubCheckPublicationRepository,
)
from orchestrator.workers.celery_app import celery_app
from orchestrator.workers.db import run_async

# Bounded batch size (design: "Dispatch and lease") — an explicit, named
# cap on each sweep's `claim_due(limit=...)` call, never an unbounded claim.
GITHUB_CHECKS_SWEEP_BATCH_SIZE = 25

# 5-minute lease: long enough for PR5's real HTTP delivery call to complete,
# short enough that a delivery worker dying before it wakes up only strands
# its claimed rows for a few sweep cycles, not indefinitely.
GITHUB_CHECKS_LEASE_DURATION = timedelta(minutes=5)


def _sweep_owner_id(task: Task) -> str:
    """A stable per-invocation owner identifier for `claim_due`'s
    owner-CAS: `<worker-hostname>:<task-id>`. Distinguishes concurrent
    sweeps across workers/invocations without inventing a new identity
    scheme — both fields come straight from Celery's own request context.
    """
    request = task.request
    hostname = request.hostname or "unknown-worker"
    task_id = request.id or uuid.uuid4().hex
    return f"{hostname}:{task_id}"


async def _claim_due_publications(session: AsyncSession, owner: str, lease_until: datetime) -> int:
    """Claim up to `GITHUB_CHECKS_SWEEP_BATCH_SIZE` due rows for `owner` via
    PR2's `claim_due` — no delivery call exists here (see module docstring).
    Returns the count claimed; the caller has nothing else to do with them
    in this PR.
    """
    repository = SqlAlchemyGitHubCheckPublicationRepository(session)
    claimed = await repository.claim_due(
        limit=GITHUB_CHECKS_SWEEP_BATCH_SIZE, owner=owner, lease_until=lease_until
    )
    await session.commit()
    return len(claimed)


@celery_app.task(bind=True)  # type: ignore[untyped-decorator]
def sweep_github_check_publications_task(self: Task) -> int:
    """Beat-scheduled entry point (60s, `celery_app.py`). Returns `0`
    without any DB/network/auth I/O while
    `settings.github_checks_delivery_enabled` is `False` (default); the
    flag check happens BEFORE `run_async`/`claim_due` is ever called.
    """
    settings = get_settings()
    if not settings.github_checks_delivery_enabled:
        return 0

    owner = _sweep_owner_id(self)
    lease_until = datetime.now(UTC).replace(tzinfo=None) + GITHUB_CHECKS_LEASE_DURATION
    return run_async(lambda session: _claim_due_publications(session, owner, lease_until))
