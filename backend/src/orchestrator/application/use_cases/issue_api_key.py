"""`issue_api_key` — pairs task 3.4's `generate_api_key` with `ApiKeyPort`, thin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.ports.api_key_port import ApiKeyPort
from orchestrator.infrastructure.security.api_key import generate_api_key


async def issue_api_key(api_key_port: ApiKeyPort, user_id: uuid.UUID) -> tuple[ApiKey, str]:
    """Generate, persist, and return a new `ApiKey` for `user_id` plus its one-time raw key."""
    generated = generate_api_key()
    now = datetime.now(UTC).replace(tzinfo=None)
    api_key = ApiKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key_prefix=generated.key_prefix,
        hashed_key=generated.hashed_key,
        created_at=now,
    )
    created = await api_key_port.create(api_key)
    return created, generated.raw_key
