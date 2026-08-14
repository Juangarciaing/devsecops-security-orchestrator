"""`sweep_github_check_publications_task` — claims due GitHub Checks outbox
rows and delivers each within the SAME sweep invocation (github-checks-
publisher PR6c, design: "Dispatch and lease" + "Retry classification").

`Settings.github_checks_delivery_enabled` (default `False`) gates the ENTIRE
claim+deliver step (PR4's fail-closed gate, unchanged). Delivery composes
PR5b/PR5c's App-JWT/`GitHubChecksHttpClient` for the HTTP call and PR6's
`classify_publish_failure` for the retry/dead-letter decision — a retried
row's next attempt is deferred to a LATER sweep cycle via `reschedule`'s
`lease_until`, never an in-process sleep. Logs never include
`owner`/`repo`/payload content — publication id and `scan_run_id` only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx
from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.github_check_publication import GitHubCheckPublication
from orchestrator.domain.services.github_check_intent import github_check_external_id
from orchestrator.infrastructure.config.settings import Settings, get_settings
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.github_check_publication_repository import (
    SqlAlchemyGitHubCheckPublicationRepository,
)
from orchestrator.infrastructure.db.repositories.github_repository_installation_repository import (
    SqlAlchemyGitHubRepositoryInstallationRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.github.app_token_provider import GitHubAppTokenProvider
from orchestrator.infrastructure.github.checks_client import GitHubChecksHttpClient
from orchestrator.infrastructure.observability.metrics import (
    record_github_check_publication_outcome,
    record_github_check_sweep_run,
)
from orchestrator.workers.celery_app import celery_app
from orchestrator.workers.db import run_async
from orchestrator.workers.github_checks_retry import classify_publish_failure

logger = get_task_logger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"

# Bounded batch size (design: "Dispatch and lease") — an explicit, named
# cap on each sweep's `claim_due(limit=...)` call, never an unbounded claim.
GITHUB_CHECKS_SWEEP_BATCH_SIZE = 25

# 5-minute lease: long enough for a real HTTP delivery call to complete,
# short enough that a delivery worker dying mid-flight only strands its
# claimed rows for a few sweep cycles, not indefinitely.
GITHUB_CHECKS_LEASE_DURATION = timedelta(minutes=5)


def _sweep_owner_id(task: Task) -> str:
    """A stable per-invocation owner identifier for `claim_due`'s
    owner-CAS: `<worker-hostname>:<task-id>`."""
    request = task.request
    hostname = request.hostname or "unknown-worker"
    task_id = request.id or uuid.uuid4().hex
    return f"{hostname}:{task_id}"


async def _claim_due_publications(
    session: AsyncSession, owner: str, lease_until: datetime
) -> list[GitHubCheckPublication]:
    """Claim up to `GITHUB_CHECKS_SWEEP_BATCH_SIZE` due rows for `owner` via
    PR2's `claim_due`, committing the claim before any delivery attempt."""
    repository = SqlAlchemyGitHubCheckPublicationRepository(session)
    claimed = await repository.claim_due(
        limit=GITHUB_CHECKS_SWEEP_BATCH_SIZE, owner=owner, lease_until=lease_until
    )
    await session.commit()
    return claimed


def _build_http_client() -> httpx.AsyncClient:
    """Test seam: production always talks to the real GitHub API; tests
    monkeypatch/inject an `httpx.MockTransport` instead (never a real
    network call)."""
    return httpx.AsyncClient(base_url=GITHUB_API_BASE_URL)


def _build_checks_client(
    settings: Settings, session: AsyncSession, http_client: httpx.AsyncClient
) -> GitHubChecksHttpClient:
    """Compose PR5b's token provider + PR5c's adapter. `github_app_id`/
    `github_app_private_key_file` are guaranteed set here — `Settings`'s own
    validator requires both whenever `github_checks_delivery_enabled` is
    `True`, the only gate past which this function is reached."""
    assert settings.github_app_id is not None and settings.github_app_private_key_file is not None
    token_provider = GitHubAppTokenProvider(
        app_id=settings.github_app_id,
        private_key_file=settings.github_app_private_key_file,
        http_client=http_client,
    )
    installation_port = SqlAlchemyGitHubRepositoryInstallationRepository(session)
    return GitHubChecksHttpClient(
        token_provider=token_provider,
        installation_port=installation_port,
        http_client=http_client,
    )


async def _deliver_one(
    session: AsyncSession,
    client: GitHubChecksHttpClient,
    publication: GitHubCheckPublication,
    owner: str,
) -> None:
    """Attempt delivery of one claimed row: mark it `DELIVERED`, `reschedule`
    it for a later sweep, or `mark_dead` it, per `classify_publish_failure`.
    `external_id` is always derived fresh via `github_check_external_id`
    (deterministic in `scan_run_id` alone); `check_run_id` reuses the
    persisted value if this row was ever delivered before (currently never,
    given the claim lifecycle, but `publish()`'s own paginated
    lookup-before-create is still the safety net for a prior
    successful-but-unrecorded create either way)."""
    publication_port = SqlAlchemyGitHubCheckPublicationRepository(session)
    attempt_count = publication.attempt_count + 1

    scan_run = await SqlAlchemyScanRunRepository(session).get_by_id(publication.scan_run_id)
    repository = (
        await SqlAlchemyCodeRepositoryRepository(session).get_by_id(scan_run.repository_id)
        if scan_run is not None and scan_run.repository_id is not None
        else None
    )
    if scan_run is None or scan_run.commit_sha is None or repository is None:
        # A corrupted/unexpected invariant (eligibility already required a
        # GITHUB provider + resolved commit_sha; the FK is ON DELETE
        # CASCADE) is dead-lettered like any other terminal failure —
        # NEVER an uncaught crash. An uncaught exception here would escape
        # `_run_sweep`'s loop before `attempt_count` was ever persisted, so
        # `classify_publish_failure`'s MAX_ATTEMPTS cap would never apply
        # and the same row would crash every lease cycle forever.
        await publication_port.mark_dead(
            publication.id,
            owner,
            attempt_count=attempt_count,
            dead_letter_reason="missing_scan_run_or_repository",
        )
        logger.warning(
            "github_check_publication %s dead-lettered reason=missing_scan_run_or_repository "
            "scan_run_id=%s",
            publication.id,
            publication.scan_run_id,
        )
        record_github_check_publication_outcome("dead")
        return

    started = monotonic()
    try:
        published = await client.publish(
            repository_id=repository.id,
            owner=repository.owner,
            repo=repository.name,
            head_sha=scan_run.commit_sha,
            check_name=publication.check_name,
            external_id=github_check_external_id(publication.scan_run_id),
            check_run_id=publication.check_run_id,
            outcome=publication.outcome,
            summary=publication.payload_summary,
        )
    except Exception as exc:
        decision = classify_publish_failure(exc, attempt_count)
        if decision.should_retry:
            assert decision.delay_seconds is not None
            lease_until = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                seconds=decision.delay_seconds
            )
            await publication_port.reschedule(
                publication.id, owner, lease_until=lease_until, attempt_count=attempt_count
            )
            logger.info(
                "github_check_publication %s rescheduled attempt=%d scan_run_id=%s",
                publication.id,
                attempt_count,
                publication.scan_run_id,
            )
            record_github_check_publication_outcome("retried")
            return
        assert decision.dead_letter_reason is not None
        await publication_port.mark_dead(
            publication.id,
            owner,
            attempt_count=attempt_count,
            dead_letter_reason=decision.dead_letter_reason,
        )
        logger.warning(
            "github_check_publication %s dead-lettered reason=%s scan_run_id=%s",
            publication.id,
            decision.dead_letter_reason,
            publication.scan_run_id,
        )
        record_github_check_publication_outcome("dead")
        return

    await publication_port.mark_delivered(
        publication.id,
        owner,
        external_id=published.external_id,
        check_run_id=published.check_run_id,
    )
    logger.info(
        "github_check_publication %s delivered scan_run_id=%s",
        publication.id,
        publication.scan_run_id,
    )
    record_github_check_publication_outcome("delivered", monotonic() - started)


async def _run_sweep(
    session: AsyncSession,
    settings: Settings,
    owner: str,
    lease_until: datetime,
    *,
    http_client_factory: Callable[[], httpx.AsyncClient] = _build_http_client,
) -> int:
    """Claim due rows, then deliver each within this SAME invocation (design:
    no in-process retry sleep — `reschedule`'s `lease_until` alone defers a
    retried row to a LATER sweep cycle, never a synchronous wait here)."""
    claimed = await _claim_due_publications(session, owner, lease_until)
    if not claimed:
        return 0

    async with http_client_factory() as http_client:
        client = _build_checks_client(settings, session, http_client)
        for publication in claimed:
            await _deliver_one(session, client, publication, owner)
            await session.commit()  # per row, not batched — survives a later row raising
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
    claimed_count = run_async(lambda session: _run_sweep(session, settings, owner, lease_until))
    record_github_check_sweep_run(claimed_count)
    return claimed_count
