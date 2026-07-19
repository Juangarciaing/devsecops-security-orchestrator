"""`ingest_webhook` use case — single outcome authority for GitHub webhook
intake (Module 10 design D3).

Records EVERY inbound delivery to `WebhookDeliveryPort` exactly once, except
the replay/duplicate branch, which explicitly does NOT re-record (design data
flow: "exists(delivery_id) -> return DUPLICATE (no re-record)"). The router
only maps the returned `WebhookOutcome` to an HTTP status (D3) — it holds NO
branching logic of its own beyond that mapping and the D4 401 return-not-raise
requirement.

`delivery_id` is recorded as `None` for `REJECTED_SIGNATURE` and
`IGNORED_EVENT` even when the `X-GitHub-Delivery` header was present: both
outcomes are reached BEFORE the `exists()` idempotency checkpoint, so
recording the real id there could either collide with a later legitimate
push carrying the same id, or violate the `delivery_id` UNIQUE constraint on
a retried rejected/ignored request. Every outcome downstream of the
`exists()` check (`INVALID_PAYLOAD`, `IGNORED_UNKNOWN_REPO`,
`IGNORED_INACTIVE_REPO`, `IGNORED_NON_DEFAULT_BRANCH`, `ACCEPTED`) already
passed that idempotency gate, so it is safe to record the real id there.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError

from orchestrator.application.dto.github_webhook import GitHubPushPayload
from orchestrator.application.use_cases.trigger_scan import trigger_scan
from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.ports.webhook_delivery_port import WebhookDeliveryPort
from orchestrator.domain.value_objects.enums import RepositoryProvider, WebhookOutcome

_PUSH_EVENT = "push"


async def ingest_webhook(
    webhook_delivery_port: WebhookDeliveryPort,
    repository_port: CodeRepositoryPort,
    scan_run_port: ScanRunPort,
    scan_task_port: ScanTaskPort,
    *,
    signature_valid: bool,
    raw_body: bytes,
    event_type: str | None,
    delivery_id: str | None,
    source_ip: str | None,
) -> tuple[WebhookOutcome, uuid.UUID | None]:
    """Process one inbound GitHub webhook HTTP request end-to-end.

    Returns `(outcome, task_id)`. `task_id` is only non-`None` when a NEW
    `ScanTask` was created by this call (i.e. `trigger_scan` reports
    `created=True`) — the router only enqueues `.delay()` in that case.
    Never raises: `GitHubPushPayload` parse failures are caught and recorded
    as `INVALID_PAYLOAD` rather than propagated.
    """

    async def _record(
        outcome: WebhookOutcome,
        *,
        recorded_delivery_id: str | None = None,
        repository_full_name: str | None = None,
        ref: str | None = None,
        commit_sha: str | None = None,
    ) -> None:
        await webhook_delivery_port.record(
            WebhookDelivery(
                id=uuid.uuid4(),
                signature_valid=signature_valid,
                outcome=outcome,
                received_at=datetime.now(UTC).replace(tzinfo=None),
                delivery_id=recorded_delivery_id,
                event_type=event_type,
                source_ip=source_ip,
                repository_full_name=repository_full_name,
                ref=ref,
                commit_sha=commit_sha,
            )
        )

    if not signature_valid:
        await _record(WebhookOutcome.REJECTED_SIGNATURE)
        return WebhookOutcome.REJECTED_SIGNATURE, None

    if event_type != _PUSH_EVENT:
        await _record(WebhookOutcome.IGNORED_EVENT)
        return WebhookOutcome.IGNORED_EVENT, None

    if delivery_id is not None and await webhook_delivery_port.exists(delivery_id):
        return WebhookOutcome.DUPLICATE, None

    try:
        payload = GitHubPushPayload.model_validate_json(raw_body)
    except ValidationError:
        await _record(WebhookOutcome.INVALID_PAYLOAD, recorded_delivery_id=delivery_id)
        return WebhookOutcome.INVALID_PAYLOAD, None

    repository = await repository_port.get_by_identity(
        RepositoryProvider.GITHUB, payload.owner, payload.name
    )
    if repository is None:
        await _record(
            WebhookOutcome.IGNORED_UNKNOWN_REPO,
            recorded_delivery_id=delivery_id,
            repository_full_name=payload.repository.full_name,
            ref=payload.ref,
            commit_sha=payload.commit_sha,
        )
        return WebhookOutcome.IGNORED_UNKNOWN_REPO, None

    if not repository.is_active:
        await _record(
            WebhookOutcome.IGNORED_INACTIVE_REPO,
            recorded_delivery_id=delivery_id,
            repository_full_name=payload.repository.full_name,
            ref=payload.ref,
            commit_sha=payload.commit_sha,
        )
        return WebhookOutcome.IGNORED_INACTIVE_REPO, None

    expected_ref = f"refs/heads/{repository.default_branch}"
    if payload.ref != expected_ref:
        await _record(
            WebhookOutcome.IGNORED_NON_DEFAULT_BRANCH,
            recorded_delivery_id=delivery_id,
            repository_full_name=payload.repository.full_name,
            ref=payload.ref,
            commit_sha=payload.commit_sha,
        )
        return WebhookOutcome.IGNORED_NON_DEFAULT_BRANCH, None

    run, created = await trigger_scan(
        repository_port,
        scan_run_port,
        scan_task_port,
        repository.id,
        commit_sha=payload.commit_sha,
        trigger="webhook",
    )

    task_id: uuid.UUID | None = None
    if created:
        tasks = await scan_task_port.list_by_scan_run(run.id)
        task_id = tasks[0].id

    await _record(
        WebhookOutcome.ACCEPTED,
        recorded_delivery_id=delivery_id,
        repository_full_name=payload.repository.full_name,
        ref=payload.ref,
        commit_sha=payload.commit_sha,
    )
    return WebhookOutcome.ACCEPTED, task_id
