"""`ApiKeyModel` ORM mapping.

Mirrors `domain.entities.api_key.ApiKey`. Belongs to one `UserModel` via
`user_id`, `ON DELETE CASCADE`. `UNIQUE (key_prefix)` — the non-secret lookup
id. `INDEX(user_id)` for listing a user's keys.

Deliberately has NO `updated_at` column (narrow exception to the rest of the
schema's convention, mirroring the `ApiKey` domain entity docstring) — the
only mutable transitions are `last_used_at` and `revoked_at`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.infrastructure.db.base import Base


class ApiKeyModel(Base):
    """ORM mapping for the `api_keys` table."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
