"""`/api/v1/webhooks` endpoints:

- `POST /api/v1/webhooks/github` — GitHub push webhook intake.
- `GET /api/v1/webhooks/deliveries` — admin-gated read path over the
  append-only delivery audit log (frontend-expansion PR4, design D8/D9).

`POST /github` deliberately has NO `get_current_user` guard: the HMAC-SHA256
signature (`X-Hub-Signature-256`, verified by `verify_webhook_signature`) IS
the auth for this endpoint (design D2/D3). `ingest_webhook` is the single
outcome authority (D3) — this router does nothing but map its returned
`WebhookOutcome` to an HTTP status and, on `REJECTED_SIGNATURE`, return
(never raise) a 401.

D4: the 401 path returns a `JSONResponse` directly rather than raising
`ProblemException`. `get_db_session` (`infrastructure/db/session.py`'s
`get_session()`) only commits on a normal (non-exception) return from the
request — raising here would trigger its exception-path rollback and
discard the `signature_valid=false` audit row `ingest_webhook` already
flushed for this same request.

`GET /deliveries` requires `require_role(ADMIN)`, not just `get_current_user`
(design D8): `WebhookDeliveryRead` mirrors the entity including `source_ip`,
which is not appropriate for a `member` to read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies.auth import require_role
from orchestrator.api.v1.dependencies.db import get_db_session
from orchestrator.api.v1.dependencies.webhook import SignatureCheck, verify_webhook_signature
from orchestrator.api.v1.errors.problem import ProblemDetail
from orchestrator.application.dto.webhook_delivery import WebhookDeliveryRead
from orchestrator.application.use_cases.ingest_webhook import ingest_webhook
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole, WebhookOutcome
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)
from orchestrator.infrastructure.db.repositories.webhook_delivery_repository import (
    SqlAlchemyWebhookDeliveryRepository,
)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

_EVENT_HEADER = "X-GitHub-Event"
_DELIVERY_HEADER = "X-GitHub-Delivery"
_PROBLEM_JSON = "application/problem+json"


@router.post("/github")
async def github_webhook_endpoint(
    request: Request,
    check: SignatureCheck = Depends(verify_webhook_signature),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> JSONResponse:
    webhook_delivery_port = SqlAlchemyWebhookDeliveryRepository(session)
    repository_port = SqlAlchemyCodeRepositoryRepository(session)
    scan_run_port = SqlAlchemyScanRunRepository(session)
    scan_task_port = SqlAlchemyScanTaskRepository(session)

    outcome, task_id = await ingest_webhook(
        webhook_delivery_port,
        repository_port,
        scan_run_port,
        scan_task_port,
        signature_valid=check.valid,
        raw_body=check.raw_body,
        event_type=request.headers.get(_EVENT_HEADER),
        delivery_id=request.headers.get(_DELIVERY_HEADER),
        source_ip=request.client.host if request.client is not None else None,
    )

    if outcome is WebhookOutcome.REJECTED_SIGNATURE:
        # D4 — see module docstring: return, never raise.
        return JSONResponse(
            status_code=401,
            content=ProblemDetail(
                title="Unauthorized",
                status=401,
                detail="Invalid webhook signature",
            ).model_dump(exclude_none=True),
            media_type=_PROBLEM_JSON,
        )

    if task_id is not None:
        await session.commit()  # D4 parity with scans.py: commit BEFORE enqueue

        # Imported lazily — same reason as `scans.py`'s call site: importing
        # `celery_app.py` at module import time forces eager `Settings()`
        # resolution before test env vars are populated.
        from orchestrator.workers.tasks.process_scan import process_scan_task

        process_scan_task.delay(str(task_id))

    return JSONResponse(status_code=200, content={"outcome": outcome.value})


@router.get("/deliveries", response_model=list[WebhookDeliveryRead])
async def list_webhook_deliveries_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_role(UserRole.ADMIN)),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[WebhookDeliveryRead]:
    webhook_delivery_port = SqlAlchemyWebhookDeliveryRepository(session)
    deliveries = await webhook_delivery_port.list_recent(limit, offset)
    return [WebhookDeliveryRead.from_entity(delivery) for delivery in deliveries]
