"""`WebhookDeliveryModel` ORM mapping.

Mirrors `domain.entities.webhook_delivery.WebhookDelivery`. Append-only audit
table — no FK to `code_repositories` (a delivery may reference an unknown or
unregistered repo, which is itself an outcome worth auditing) and no
`updated_at` column (rows are written once, never mutated).

`delivery_id` is `UNIQUE` but `nullable=True` (Module 10 design D-data-model):
a request with a tampered or missing signature may arrive without a usable
`X-GitHub-Delivery` header, and Postgres allows arbitrarily many `NULL`
values under a `UNIQUE` constraint, so repeated rejected/header-less rows
never collide. `exists()` is only ever consulted for signature-valid
deliveries, so replay detection stays scoped to genuine GitHub redeliveries.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import WebhookOutcome
from orchestrator.infrastructure.db.base import Base


class WebhookDeliveryModel(Base):
    """ORM mapping for the `webhook_deliveries` table."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome: Mapped[WebhookOutcome] = mapped_column(
        SAEnum(WebhookOutcome, name="webhook_outcome", native_enum=True),
        nullable=False,
    )
    repository_full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ref: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
