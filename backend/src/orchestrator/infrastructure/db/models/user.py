"""`UserModel` ORM mapping.

Mirrors `domain.entities.user.User`. `email` is the unique login identity.
`role` is a native Postgres enum (`user_role`).

Note: `SAEnum(UserRole, ...)` stores each member's `.name` (uppercase
`ADMIN`/`MEMBER`) in the native Postgres enum, not its lowercase `.value`
(`admin`/`member`), since no `values_callable` is passed. This is
SQLAlchemy's default behavior and matches every other native enum mapping
in this codebase (see `ScannerType`/`FindingSeverity`/etc. in
`infrastructure/db/models/`). Harmless: the mapper round-trips
transparently in Python, and `UserRole` is never queried by raw SQL
expecting lowercase values.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, func, true
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.db.base import Base


class UserModel(Base):
    """ORM mapping for the `users` table."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.MEMBER,
        server_default=UserRole.MEMBER.name,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
