"""ApiKey entity — `is_active` is derived from `revoked_at`; never holds a plaintext key."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.api_key import ApiKey


def _make_api_key(**overrides: object) -> ApiKey:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "key_prefix": "dso_a1b2c3d4",
        "hashed_key": "a" * 64,
        "created_at": now,
        "last_used_at": None,
        "revoked_at": None,
    }
    defaults.update(overrides)
    return ApiKey(**defaults)  # type: ignore[arg-type]


def test_is_active_true_when_revoked_at_is_none() -> None:
    api_key = _make_api_key(revoked_at=None)

    assert api_key.is_active is True


def test_is_active_false_when_revoked_at_is_set() -> None:
    revoked_at = datetime.now(UTC)

    api_key = _make_api_key(revoked_at=revoked_at)

    assert api_key.is_active is False


def test_fields_are_stored_as_provided() -> None:
    now = datetime.now(UTC)
    key_id = uuid.uuid4()
    user_id = uuid.uuid4()
    last_used_at = datetime.now(UTC)

    api_key = _make_api_key(
        id=key_id,
        user_id=user_id,
        key_prefix="dso_ffeeddcc",
        hashed_key="b" * 64,
        created_at=now,
        last_used_at=last_used_at,
        revoked_at=None,
    )

    assert api_key.id == key_id
    assert api_key.user_id == user_id
    assert api_key.key_prefix == "dso_ffeeddcc"
    assert api_key.hashed_key == "b" * 64
    assert api_key.created_at == now
    assert api_key.last_used_at == last_used_at
    assert api_key.revoked_at is None


def test_entity_has_no_updated_at_field() -> None:
    field_names = {f.name for f in dataclasses.fields(ApiKey)}

    assert "updated_at" not in field_names
    assert "revoked_at" in field_names


def test_entity_never_holds_a_plaintext_key_field() -> None:
    field_names = {f.name for f in dataclasses.fields(ApiKey)}

    assert "hashed_key" in field_names
    assert "key" not in field_names
    assert "plaintext_key" not in field_names
