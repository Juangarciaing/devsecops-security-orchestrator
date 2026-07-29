"""`CredentialAccessLogModel` ORM mapping.

Mirrors `domain.entities.credential_access_log.CredentialAccessLog`.
Append-only audit table — no FK to `code_repositories` (the trail must
outlive repository deletion, same rationale as `webhook_deliveries` having
no FK) and no `updated_at` column (rows are written once, never mutated).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind
from orchestrator.infrastructure.db.base import Base


class CredentialAccessLogModel(Base):
    """ORM mapping for the `credential_access_log` table."""

    __tablename__ = "credential_access_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    scan_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    credential_kind: Mapped[CredentialKind] = mapped_column(
        SAEnum(CredentialKind, name="credential_kind", native_enum=True), nullable=False
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    outcome: Mapped[CredentialAccessOutcome] = mapped_column(
        SAEnum(CredentialAccessOutcome, name="credential_access_outcome", native_enum=True),
        nullable=False,
    )
    accessed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
