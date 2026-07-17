"""Pydantic v2 I/O schemas for `ApiKey`.

Application-boundary DTOs. `ApiKeyRead` mirrors `domain.entities.api_key.ApiKey`
EXCEPT `hashed_key` — it MUST NEVER be present in a response.
`ApiKeyCreatedResponse` is the ONLY response shape that carries the plaintext
`raw_key`, returned once at creation and never persisted or logged.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.api_key import ApiKey


class ApiKeyRead(BaseModel):
    """Output schema mirroring `ApiKey` minus `hashed_key` (never exposed)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    user_id: uuid.UUID
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: ApiKey) -> ApiKeyRead:
        """Build an `ApiKeyRead` from a domain `ApiKey` entity, dropping `hashed_key`."""
        return cls(
            id=entity.id,
            user_id=entity.user_id,
            key_prefix=entity.key_prefix,
            is_active=entity.is_active,
            created_at=entity.created_at,
            last_used_at=entity.last_used_at,
            revoked_at=entity.revoked_at,
        )


class ApiKeyCreatedResponse(BaseModel):
    """Response returned ONLY at issuance time: carries the one-time plaintext `raw_key`."""

    model_config = ConfigDict(extra="forbid")

    api_key: ApiKeyRead
    raw_key: str
