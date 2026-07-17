"""ApiKey domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ApiKey:
    """A long-lived credential issued to a `User` for programmatic access.

    Belongs to exactly one `User` (`user_id`). Only `hashed_key` (a SHA-256
    hash of the secret) is ever stored — the plaintext key is returned once,
    at creation, and never persisted or logged. `is_active` is derived from
    `revoked_at`, not stored directly.

    Deliberately has NO `updated_at` (narrow exception to the rest of the
    domain's convention): the only mutable transitions are `last_used_at`
    (touched on use) and `revoked_at` (set once on revocation).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    key_prefix: str
    hashed_key: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
