"""WebhookDelivery domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import WebhookOutcome


@dataclass(slots=True)
class WebhookDelivery:
    """An append-only audit record of one inbound GitHub webhook HTTP request.

    Every delivery — accepted, ignored, or rejected — is recorded exactly
    once by `IngestWebhookUseCase` (Module 10 design D3). `delivery_id`
    (the `X-GitHub-Delivery` header) is nullable: a request with a tampered
    or missing signature may arrive without any usable headers at all, but
    the audit row must still be written.

    Deliberately has NO `updated_at` field: this row is written once and
    never mutated, matching the `webhook_deliveries` table's append-only
    design.
    """

    id: uuid.UUID
    signature_valid: bool
    outcome: WebhookOutcome
    received_at: datetime
    delivery_id: str | None = None
    event_type: str | None = None
    source_ip: str | None = None
    repository_full_name: str | None = None
    ref: str | None = None
    commit_sha: str | None = None
