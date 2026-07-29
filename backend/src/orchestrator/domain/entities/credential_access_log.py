"""CredentialAccessLog domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind


@dataclass(slots=True)
class CredentialAccessLog:
    """An append-only audit record of one decrypt-and-use attempt against a
    stored repository credential (design D7), mirroring the
    `WebhookDelivery` audit entity's conventions.

    No FK to `code_repositories` — the trail must outlive repository
    deletion, same rationale as `webhook_deliveries` having no FK.

    Deliberately has NO `updated_at` field: this row is written once and
    never mutated, matching `webhook_deliveries`' append-only design. Never
    stores the plaintext or ciphertext itself — only the outcome of one
    access attempt.
    """

    id: uuid.UUID
    repository_id: uuid.UUID
    credential_kind: CredentialKind
    actor: str
    outcome: CredentialAccessOutcome
    accessed_at: datetime
    scan_task_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
