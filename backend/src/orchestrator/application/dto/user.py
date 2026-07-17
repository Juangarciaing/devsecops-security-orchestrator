"""Pydantic v2 I/O schemas for `User`.

Application-boundary DTOs. `UserRead` mirrors `domain.entities.user.User`
EXCEPT `hashed_password` — it MUST NEVER be present, so a plaintext-adjacent
value never leaves the application boundary via an HTTP response.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole


class UserCreate(BaseModel):
    """Input schema for creating a `User`. Carries the plaintext `password` in transit only."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    role: UserRole = UserRole.MEMBER


class UserRead(BaseModel):
    """Output schema mirroring `User` minus `hashed_password` (never exposed)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: User) -> UserRead:
        """Build a `UserRead` from a domain `User` entity, dropping `hashed_password`."""
        return cls(
            id=entity.id,
            email=entity.email,
            role=entity.role,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
