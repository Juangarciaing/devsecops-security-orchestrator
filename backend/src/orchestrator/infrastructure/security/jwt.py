"""Stateless HS256 JWT issuance/validation (D4: `pyjwt`, `sub`/`role`/`exp`/`iat` claims).

`create_access_token`/`decode_access_token` are the ONLY place token claims are
constructed or parsed — callers never touch `pyjwt` directly. `decode_access_token`
raises `ValueError` (not the underlying `pyjwt` exception type) so callers (the
`get_current_user` DI guard) have one exception type to catch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.config.settings import get_settings

_ALGORITHM = "HS256"


@dataclass(slots=True, frozen=True)
class TokenClaims:
    """Decoded, validated JWT claims."""

    sub: str
    role: UserRole

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(self.sub)


def create_access_token(user: User) -> str:
    """Issue an HS256 JWT for `user` with `sub`/`role`/`iat`/`exp` claims."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    """Decode and validate `token`. Raises `ValueError` on any invalid/expired token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("invalid token") from exc

    try:
        return TokenClaims(sub=payload["sub"], role=UserRole(payload["role"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid token claims") from exc
