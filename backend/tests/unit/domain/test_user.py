"""User entity — holds only hashed_password, never plaintext; fields stored as provided.

Duplicate-email rejection is a persistence-port concern (uniqueness constraint),
not an entity concern — no test for it lives here.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole


def _make_user(**overrides: object) -> User:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": "admin@example.com",
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$salt$hash",
        "role": UserRole.ADMIN,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def test_fields_are_stored_as_provided() -> None:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()

    user = _make_user(
        id=user_id,
        email="member@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$salt2$hash2",
        role=UserRole.MEMBER,
        is_active=False,
        created_at=now,
        updated_at=now,
    )

    assert user.id == user_id
    assert user.email == "member@example.com"
    assert user.hashed_password == "$argon2id$v=19$m=65536,t=3,p=4$salt2$hash2"
    assert user.role is UserRole.MEMBER
    assert user.is_active is False
    assert user.created_at == now
    assert user.updated_at == now


def test_admin_role_is_stored_distinctly_from_member() -> None:
    admin = _make_user(role=UserRole.ADMIN)
    member = _make_user(role=UserRole.MEMBER)

    assert admin.role is UserRole.ADMIN
    assert member.role is UserRole.MEMBER
    assert admin.role.value != member.role.value


def test_entity_never_holds_a_plaintext_password_field() -> None:
    field_names = {f.name for f in dataclasses.fields(User)}

    assert "hashed_password" in field_names
    assert "password" not in field_names
