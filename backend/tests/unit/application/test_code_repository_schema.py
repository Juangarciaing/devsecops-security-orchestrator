"""CodeRepositoryRead/Create/Update schema — round-trip and validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.code_repository import (
    CodeRepositoryCreate,
    CodeRepositoryRead,
    CodeRepositoryUpdate,
)
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
        "credential_ref": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_all_fields() -> None:
    entity = _make_entity(credential_ref="vault://secret/orchestrator")

    schema = CodeRepositoryRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.credential_ref == "vault://secret/orchestrator"
    assert schema.is_active is True


def test_round_trip_preserves_all_fields_with_different_values() -> None:
    entity = _make_entity(
        provider=RepositoryProvider.GITLAB,
        owner="acme",
        name="widgets",
        clone_url="https://gitlab.com/acme/widgets.git",
        default_branch="develop",
        credential_ref=None,
        is_active=False,
    )

    schema = CodeRepositoryRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.provider is RepositoryProvider.GITLAB
    assert schema.credential_ref is None
    assert schema.is_active is False


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
            credential_ref=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )


def test_create_schema_accepts_omitted_credential_ref() -> None:
    schema = CodeRepositoryCreate(
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
    )

    assert schema.credential_ref is None


def test_create_schema_accepts_explicit_credential_ref() -> None:
    schema = CodeRepositoryCreate(
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
        credential_ref="vault://secret/widgets",
    )

    assert schema.credential_ref == "vault://secret/widgets"


def test_create_schema_rejects_is_active() -> None:
    """`is_active` always starts `True` server-side — not client-settable."""
    with pytest.raises(ValidationError):
        CodeRepositoryCreate(
            provider=RepositoryProvider.GITHUB,
            owner="acme",
            name="widgets",
            clone_url="https://github.com/acme/widgets.git",
            default_branch="main",
            is_active=False,  # type: ignore[call-arg]
        )


def test_update_schema_accepts_mutable_fields_only() -> None:
    schema = CodeRepositoryUpdate(
        clone_url="https://github.com/acme/widgets-new.git",
        default_branch="develop",
        credential_ref="vault://secret/widgets-new",
    )

    assert schema.clone_url == "https://github.com/acme/widgets-new.git"
    assert schema.default_branch == "develop"
    assert schema.credential_ref == "vault://secret/widgets-new"


def test_update_schema_all_fields_are_optional() -> None:
    schema = CodeRepositoryUpdate()

    assert schema.clone_url is None
    assert schema.default_branch is None
    assert schema.credential_ref is None


@pytest.mark.parametrize("identity_field", ["provider", "owner", "name"])
def test_update_schema_rejects_identity_fields(identity_field: str) -> None:
    with pytest.raises(ValidationError):
        CodeRepositoryUpdate(**{identity_field: "should-not-be-accepted"})
