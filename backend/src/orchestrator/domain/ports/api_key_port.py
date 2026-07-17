"""`ApiKeyPort` — persistence contract for `ApiKey`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.api_key import ApiKey


class ApiKeyPort(ABC):
    """Async persistence contract for the `ApiKey` aggregate."""

    @abstractmethod
    async def create(self, api_key: ApiKey) -> ApiKey:
        """Persist a new `ApiKey` and return the stored entity."""

    @abstractmethod
    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        """Return the `ApiKey` matching the given `key_prefix`, or `None` if absent."""

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        """Return every `ApiKey` belonging to the given `User`."""

    @abstractmethod
    async def revoke(self, key_id: uuid.UUID) -> ApiKey:
        """Set `revoked_at` on the given `ApiKey` and return the updated entity."""

    @abstractmethod
    async def touch(self, key_id: uuid.UUID) -> ApiKey:
        """Set `last_used_at` to now on the given `ApiKey` and return the updated entity."""
