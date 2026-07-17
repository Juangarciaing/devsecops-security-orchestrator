"""`create_user` — hash the password and reject duplicate emails, thin and port-driven."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.security.password_hasher import hash_password


class DuplicateEmailError(Exception):
    """Raised when `create_user` is called with an email that already exists."""


async def create_user(
    user_port: UserPort,
    email: str,
    password: str,
    role: UserRole = UserRole.MEMBER,
) -> User:
    """Create and persist a new `User` with a hashed password.

    Raises `DuplicateEmailError` if `email` is already registered.
    """
    existing = await user_port.get_by_email(email)
    if existing is not None:
        raise DuplicateEmailError(email)

    now = datetime.now(UTC).replace(tzinfo=None)
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    return await user_port.create(user)
