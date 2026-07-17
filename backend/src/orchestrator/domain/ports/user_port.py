"""`UserPort` — persistence contract for `User`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.user import User


class UserPort(ABC):
    """Async persistence contract for the `User` aggregate."""

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the `User` with the given id, or `None` if absent."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Return the `User` matching the given `email`, or `None` if absent."""

    @abstractmethod
    async def create(self, user: User) -> User:
        """Persist a new `User` and return the stored entity."""

    @abstractmethod
    async def list_all(self) -> list[User]:
        """Return every `User`."""
