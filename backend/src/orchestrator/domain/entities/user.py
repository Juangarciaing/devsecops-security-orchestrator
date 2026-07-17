"""User domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import UserRole


@dataclass(slots=True)
class User:
    """An authenticated principal with RBAC role `role`.

    Holds `hashed_password` only — plaintext passwords MUST NOT be accepted or
    exposed by this entity. Duplicate-email rejection is enforced by the
    persistence port (unique constraint), not by this entity.
    """

    id: uuid.UUID
    email: str
    hashed_password: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
