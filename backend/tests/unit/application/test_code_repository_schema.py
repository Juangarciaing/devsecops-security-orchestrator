"""CodeRepositoryRead/Create schema — round-trip and enum validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.code_repository import CodeRepositoryRead
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider


def _make_entity(**overrides: object) -> CodeRepository:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "gentleman-programming",
        "name": "devsecops-security-orchestrator",
        "clone_url": "https://github.com/gentleman-programming/devsecops-security-orchestrator.git",
        "default_branch": "main",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_all_fields() -> None:
    entity = _make_entity()

    schema = CodeRepositoryRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity


def test_round_trip_preserves_all_fields_with_different_values() -> None:
    entity = _make_entity(
        provider=RepositoryProvider.GITLAB,
        owner="acme",
        name="widgets",
        clone_url="https://gitlab.com/acme/widgets.git",
        default_branch="develop",
    )

    schema = CodeRepositoryRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.provider is RepositoryProvider.GITLAB


def test_invalid_provider_raises_validation_error() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        CodeRepositoryRead(
            id=uuid.uuid4(),
            provider="svn",  # type: ignore[arg-type]
            owner="acme",
            name="widgets",
            clone_url="https://example.com/acme/widgets.git",
            default_branch="main",
            created_at=now,
            updated_at=now,
        )
