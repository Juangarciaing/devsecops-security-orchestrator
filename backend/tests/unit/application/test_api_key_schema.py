"""`ApiKeyRead`/`ApiKeyCreatedResponse` schemas — `hashed_key` never leaves the boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.api_key import ApiKeyCreatedResponse, ApiKeyRead
from orchestrator.domain.entities.api_key import ApiKey


def _make_entity(**overrides: object) -> ApiKey:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "key_prefix": "dso_abcd1234",
        "hashed_key": "sha256-hash-value",
        "created_at": now,
        "last_used_at": None,
        "revoked_at": None,
    }
    defaults.update(overrides)
    return ApiKey(**defaults)  # type: ignore[arg-type]


def test_api_key_read_from_entity_never_exposes_hashed_key() -> None:
    entity = _make_entity()

    schema = ApiKeyRead.from_entity(entity)

    assert "hashed_key" not in schema.model_dump()
    assert schema.key_prefix == entity.key_prefix
    assert schema.is_active is True


def test_api_key_read_from_entity_reflects_revoked_state() -> None:
    entity = _make_entity(revoked_at=datetime.now(UTC).replace(tzinfo=None))

    schema = ApiKeyRead.from_entity(entity)

    assert schema.is_active is False
    assert schema.revoked_at is not None


def test_api_key_created_response_carries_the_one_time_raw_key() -> None:
    entity = _make_entity()

    response = ApiKeyCreatedResponse(
        api_key=ApiKeyRead.from_entity(entity), raw_key="dso_abcd1234.the-secret"
    )

    assert response.raw_key == "dso_abcd1234.the-secret"
    assert response.api_key.key_prefix == entity.key_prefix
