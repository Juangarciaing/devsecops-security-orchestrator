"""Pydantic v2 I/O schema for `WebhookDelivery`.

Application-boundary DTO. Mirrors `domain.entities.webhook_delivery.WebhookDelivery`
exactly (frontend-expansion PR4, design D8) — including `source_ip`, which is
exactly why `GET /api/v1/webhooks/deliveries` (the only route that returns
this DTO) is `require_role(ADMIN)`-gated rather than `get_current_user`-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.value_objects.enums import WebhookOutcome


class WebhookDeliveryRead(BaseModel):
    """Output schema mirroring the full `WebhookDelivery` entity."""

    model_config = ConfigDict(extra="forbid")

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

    @classmethod
    def from_entity(cls, entity: WebhookDelivery) -> WebhookDeliveryRead:
        """Build a `WebhookDeliveryRead` from a domain `WebhookDelivery` entity."""
        return cls(
            id=entity.id,
            signature_valid=entity.signature_valid,
            outcome=entity.outcome,
            received_at=entity.received_at,
            delivery_id=entity.delivery_id,
            event_type=entity.event_type,
            source_ip=entity.source_ip,
            repository_full_name=entity.repository_full_name,
            ref=entity.ref,
            commit_sha=entity.commit_sha,
        )
