"""`update_repository` use case — mutable-only, omitted-vs-null distinction, 404-on-inactive."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from orchestrator.application.dto.code_repository import CodeRepositoryUpdate
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.register_repository import (
    UnsupportedCredentialProviderError,
)
from orchestrator.application.use_cases.update_repository import (
    InvalidRepositoryUpdateError,
    update_repository,
)
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.credential_store_port import (
    CredentialSealError,
    CredentialStorePort,
    SealedCredential,
)
from orchestrator.domain.value_objects.enums import CredentialKind, RepositoryProvider
from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore

_NOW = datetime.now(UTC).replace(tzinfo=None)


def _credential_store(*, keyed: bool = True) -> FernetCredentialStore:
    key = Fernet.generate_key().decode("ascii") if keyed else None
    return FernetCredentialStore(encryption_key=key)


class _ExplodingCredentialStore(CredentialStorePort):
    """Fails the test if `seal`/`unseal` is ever called — proves a guard runs first."""

    def seal(self, plaintext: str, kind: CredentialKind) -> SealedCredential:
        raise AssertionError("seal() must not be called")

    def unseal(self, sealed: SealedCredential) -> Secret:
        raise AssertionError("unseal() must not be called")


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_kind": None,
        "credential_ciphertext": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self, repositories: list[CodeRepository]) -> None:
        self._by_id = {repo.id: repo for repo in repositories}
        self.updated: list[CodeRepository] = []

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        return self._by_id.get(repository_id)

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        raise NotImplementedError

    async def list_all(self) -> list[CodeRepository]:
        raise NotImplementedError

    async def list_active(self) -> list[CodeRepository]:
        raise NotImplementedError

    async def create(self, repository: CodeRepository) -> CodeRepository:
        raise NotImplementedError

    async def update(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        self.updated.append(repository)
        return repository

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError

    async def delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError


def test_update_repository_applies_only_provided_fields() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/widgets-new.git")

    result = asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))

    assert result.clone_url == "https://github.com/acme/widgets-new.git"
    # Omitted fields stay unchanged.
    assert result.default_branch == "main"


def test_update_repository_rejects_explicit_null_clone_url() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(clone_url=None)

    try:
        asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))
        raise AssertionError("expected InvalidRepositoryUpdateError")
    except InvalidRepositoryUpdateError:
        pass

    # Nothing was persisted — rejected before any mutation.
    assert repository_port.updated == []


def test_update_repository_rejects_explicit_null_default_branch() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(default_branch=None)

    try:
        asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))
        raise AssertionError("expected InvalidRepositoryUpdateError")
    except InvalidRepositoryUpdateError:
        pass

    assert repository_port.updated == []


def test_update_repository_raises_when_missing() -> None:
    repository_port = _FakeCodeRepositoryRepository([])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/ghost.git")

    try:
        asyncio.run(update_repository(repository_port, _credential_store(), uuid.uuid4(), update))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass


def test_update_repository_raises_when_inactive() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/ghost.git")

    try:
        asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass


# ---------------------------------------------------------------------------
# secrets-manager PR3 — re-seal-on-update, fail-closed, GitHub-only guard.
# ---------------------------------------------------------------------------


def test_update_repository_reseals_credential_old_ciphertext_replaced() -> None:
    repo = _make_repository(
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        credential_ciphertext="old-opaque-ciphertext",
    )
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential="ghp_newtoken")

    result = asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))

    assert result.credential_kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert result.credential_ciphertext is not None
    assert result.credential_ciphertext != "old-opaque-ciphertext"
    assert result.credential_ciphertext != "ghp_newtoken"


def test_update_repository_omitted_credential_leaves_existing_untouched() -> None:
    repo = _make_repository(
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        credential_ciphertext="unchanged-ciphertext",
    )
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/widgets-new.git")

    result = asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))

    assert result.credential_kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert result.credential_ciphertext == "unchanged-ciphertext"


def test_update_repository_explicit_null_credential_leaves_existing_untouched() -> None:
    repo = _make_repository(
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        credential_ciphertext="unchanged-ciphertext",
    )
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential=None)

    result = asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))

    assert result.credential_kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert result.credential_ciphertext == "unchanged-ciphertext"


def test_update_repository_missing_key_raises_and_leaves_prior_state_unchanged() -> None:
    repo = _make_repository(
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        credential_ciphertext="unchanged-ciphertext",
    )
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential="ghp_newtoken")

    with pytest.raises(CredentialSealError):
        asyncio.run(
            update_repository(repository_port, _credential_store(keyed=False), repo.id, update)
        )

    assert repository_port.updated == []
    persisted = asyncio.run(repository_port.get_by_id(repo.id))
    assert persisted is not None
    assert persisted.credential_ciphertext == "unchanged-ciphertext"


def test_update_repository_rejects_credential_for_non_github_provider() -> None:
    repo = _make_repository(provider=RepositoryProvider.GITLAB)
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential="ghp_newtoken")

    with pytest.raises(UnsupportedCredentialProviderError):
        asyncio.run(update_repository(repository_port, _credential_store(), repo.id, update))

    assert repository_port.updated == []


def test_update_repository_checks_provider_guard_before_ever_sealing() -> None:
    """Adversarial proof, mirroring `register_repository`'s: an exploding
    `CredentialStorePort` that fails the test if `seal()`/`unseal()` is ever
    called proves the GitHub-only guard runs strictly first."""
    repo = _make_repository(provider=RepositoryProvider.GITLAB)
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential="ghp_newtoken")

    with pytest.raises(UnsupportedCredentialProviderError):
        asyncio.run(
            update_repository(repository_port, _ExplodingCredentialStore(), repo.id, update)
        )

    assert repository_port.updated == []
