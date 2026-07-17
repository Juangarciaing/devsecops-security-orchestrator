"""`create_access_token`/`decode_access_token` — HS256, `sub`/`role`/`exp`/`iat` claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest

from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.security.jwt import create_access_token, decode_access_token


def _make_user(role: UserRole = UserRole.MEMBER) -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        hashed_password="irrelevant-for-this-test",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_create_access_token_roundtrips_through_decode(valid_env: None) -> None:
    user = _make_user(role=UserRole.MEMBER)

    token = create_access_token(user)
    claims = decode_access_token(token)

    assert claims.sub == str(user.id)
    assert claims.role == UserRole.MEMBER


def test_create_access_token_carries_admin_role(valid_env: None) -> None:
    user = _make_user(role=UserRole.ADMIN)

    token = create_access_token(user)
    claims = decode_access_token(token)

    assert claims.sub == str(user.id)
    assert claims.role == UserRole.ADMIN


def test_decode_access_token_rejects_expired_token(valid_env: None) -> None:
    from orchestrator.infrastructure.config.settings import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": UserRole.MEMBER.value,
        "iat": now - timedelta(minutes=settings.jwt_expiry_minutes + 5),
        "exp": now - timedelta(minutes=5),
    }
    expired_token = pyjwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")

    with pytest.raises(ValueError, match="expired"):
        decode_access_token(expired_token)


def test_decode_access_token_rejects_tampered_signature(valid_env: None) -> None:
    user = _make_user()
    token = create_access_token(user)
    header_b64, payload_b64, signature_b64 = token.split(".")

    tampered_char = "B" if signature_b64[-1] != "B" else "A"
    tampered_signature_b64 = signature_b64[:-1] + tampered_char
    tampered = f"{header_b64}.{payload_b64}.{tampered_signature_b64}"

    with pytest.raises(ValueError, match="invalid"):
        decode_access_token(tampered)


def test_decode_access_token_rejects_wrong_secret(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user()
    token = create_access_token(user)

    monkeypatch.setenv("JWT_SECRET_KEY", "a-completely-different-secret-key")
    from orchestrator.infrastructure.config.settings import get_settings

    get_settings.cache_clear()

    with pytest.raises(ValueError, match="invalid"):
        decode_access_token(token)
