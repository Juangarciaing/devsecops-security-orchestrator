"""CodeRepository entity identity and field invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider


def _make_repository(**overrides: object) -> CodeRepository:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_ref": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


def test_identity_is_provider_owner_name_tuple() -> None:
    repo = _make_repository()

    assert repo.identity() == (RepositoryProvider.GITHUB, "acme", "widgets")


def test_same_identity_different_clone_url_is_identity_conflict() -> None:
    """clone_url is NOT part of identity: same (provider, owner, name) with a
    different clone_url is still the same logical identity — a conflict, not
    two distinct repositories."""
    repo_a = _make_repository(clone_url="https://github.com/acme/widgets.git")
    repo_b = _make_repository(clone_url="git@github.com:acme/widgets.git")

    assert repo_a.identity() == repo_b.identity()
    assert repo_a.same_identity_as(repo_b) is True


def test_different_owner_is_not_identity_conflict() -> None:
    repo_a = _make_repository(owner="acme")
    repo_b = _make_repository(owner="other-org")

    assert repo_a.identity() != repo_b.identity()
    assert repo_a.same_identity_as(repo_b) is False


def test_fields_are_stored_as_provided() -> None:
    repo_id = uuid.uuid4()
    now = datetime.now(UTC)

    repo = CodeRepository(
        id=repo_id,
        provider=RepositoryProvider.GITLAB,
        owner="acme",
        name="widgets",
        clone_url="https://gitlab.com/acme/widgets.git",
        default_branch="develop",
        credential_ref="vault://secret/widgets",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    assert repo.id == repo_id
    assert repo.provider is RepositoryProvider.GITLAB
    assert repo.owner == "acme"
    assert repo.name == "widgets"
    assert repo.clone_url == "https://gitlab.com/acme/widgets.git"
    assert repo.default_branch == "develop"
    assert repo.credential_ref == "vault://secret/widgets"
    assert repo.is_active is True
    assert repo.created_at == now
    assert repo.updated_at == now


def test_credential_ref_may_be_none() -> None:
    repo = _make_repository(credential_ref=None)

    assert repo.credential_ref is None


def test_is_active_can_be_false() -> None:
    repo = _make_repository(is_active=False)

    assert repo.is_active is False
