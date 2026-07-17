"""`authenticate_user` — verify email/password against `UserPort`, thin and port-driven."""

from __future__ import annotations

from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.infrastructure.security.password_hasher import verify_password


class InvalidCredentialsError(Exception):
    """Raised when email/password do not match an active user.

    Deliberately does NOT distinguish "unknown email" from "wrong password"
    from "inactive user" — callers must not leak which case occurred.
    """


async def authenticate_user(user_port: UserPort, email: str, password: str) -> User:
    """Return the active `User` matching `email`/`password`, or raise `InvalidCredentialsError`."""
    user = await user_port.get_by_email(email)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError("Invalid email or password")
    return user
