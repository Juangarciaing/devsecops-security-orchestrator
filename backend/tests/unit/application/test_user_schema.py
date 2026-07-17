"""`UserRead`/`UserCreate` schemas — `UserRead` must never expose `hashed_password`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.user import UserCreate, UserRead
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import UserRole


def _make_entity(**overrides: object) -> User:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": "member@example.com",
        "hashed_password": "$argon2id$super-secret-hash",
        "role": UserRole.MEMBER,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def test_user_read_from_entity_never_exposes_hashed_password() -> None:
    entity = _make_entity()

    schema = UserRead.from_entity(entity)

    assert "hashed_password" not in schema.model_dump()
    assert not hasattr(schema, "hashed_password")
    assert schema.email == entity.email
    assert schema.role is UserRole.MEMBER


def test_user_read_from_entity_preserves_admin_role_and_id() -> None:
    entity = _make_entity(role=UserRole.ADMIN, email="admin@example.com")

    schema = UserRead.from_entity(entity)

    assert schema.role is UserRole.ADMIN
    assert schema.id == entity.id
    assert schema.is_active is True


def test_user_create_defaults_role_to_member() -> None:
    payload = UserCreate(email="new@example.com", password="s3cret-passw0rd")

    assert payload.role is UserRole.MEMBER
    assert payload.password == "s3cret-passw0rd"


def test_user_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        UserCreate(email="new@example.com", password="s3cret-passw0rd", is_admin=True)  # type: ignore[call-arg]
