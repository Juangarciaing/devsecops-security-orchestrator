"""`register_repository` use case — rejects duplicate identity (active or inactive)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from orchestrator.application.use_cases.register_repository import (
    DuplicateRepositoryIdentityError,
    UnsupportedCredentialProviderError,
    register_repository,
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


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self) -> None:
        self.created: list[CodeRepository] = []
        self._by_id: dict[uuid.UUID, CodeRepository] = {}

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        return self._by_id.get(repository_id)

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        for repo in self._by_id.values():
            if repo.identity() == (provider, owner, name):
                return repo
        return None

    async def list_all(self) -> list[CodeRepository]:
        return list(self._by_id.values())

    async def list_active(self) -> list[CodeRepository]:
        return [repo for repo in self._by_id.values() if repo.is_active]

    async def create(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        self.created.append(repository)
        return repository

    async def update(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        return repository

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        repo = self._by_id.get(repository_id)
        if repo is not None:
            repo.is_active = False

    async def delete(self, repository_id: uuid.UUID) -> None:
        self._by_id.pop(repository_id, None)


def test_register_repository_creates_active_repository() -> None:
    repository_port = _FakeCodeRepositoryRepository()

    created = asyncio.run(
        register_repository(
            repository_port,
            _credential_store(),
            RepositoryProvider.GITHUB,
            "acme",
            "widgets",
            "https://github.com/acme/widgets.git",
            "main",
        )
    )

    assert created.owner == "acme"
    assert created.name == "widgets"
    assert created.is_active is True
    assert created.credential_kind is None
    assert created.credential_ciphertext is None


def test_register_repository_raises_on_duplicate_active_identity() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    asyncio.run(
        register_repository(
            repository_port,
            _credential_store(),
            RepositoryProvider.GITHUB,
            "acme",
            "widgets",
            "https://github.com/acme/widgets.git",
            "main",
        )
    )

    try:
        asyncio.run(
            register_repository(
                repository_port,
                _credential_store(),
                RepositoryProvider.GITHUB,
                "acme",
                "widgets",
                "https://github.com/acme/widgets-fork.git",
                "main",
            )
        )
        raise AssertionError("expected DuplicateRepositoryIdentityError")
    except DuplicateRepositoryIdentityError:
        pass

    assert len(repository_port.created) == 1


def test_register_repository_raises_on_duplicate_soft_deleted_identity() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    created = asyncio.run(
        register_repository(
            repository_port,
            _credential_store(),
            RepositoryProvider.GITHUB,
            "acme",
            "widgets",
            "https://github.com/acme/widgets.git",
            "main",
        )
    )
    asyncio.run(repository_port.soft_delete(created.id))

    try:
        asyncio.run(
            register_repository(
                repository_port,
                _credential_store(),
                RepositoryProvider.GITHUB,
                "acme",
                "widgets",
                "https://github.com/acme/widgets-new.git",
                "main",
            )
        )
        raise AssertionError("expected DuplicateRepositoryIdentityError")
    except DuplicateRepositoryIdentityError:
        pass


# ---------------------------------------------------------------------------
# secrets-manager PR3 — seal-before-persist, fail-closed, GitHub-only guard.
# ---------------------------------------------------------------------------


def test_register_repository_seals_credential_before_persisting() -> None:
    repository_port = _FakeCodeRepositoryRepository()

    created = asyncio.run(
        register_repository(
            repository_port,
            _credential_store(),
            RepositoryProvider.GITHUB,
            "acme",
            "widgets",
            "https://github.com/acme/widgets.git",
            "main",
            credential="ghp_supersecrettoken",
        )
    )

    assert created.credential_kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert created.credential_ciphertext is not None
    assert created.credential_ciphertext != "ghp_supersecrettoken"


def test_register_repository_missing_key_raises_and_writes_no_row() -> None:
    repository_port = _FakeCodeRepositoryRepository()

    with pytest.raises(CredentialSealError):
        asyncio.run(
            register_repository(
                repository_port,
                _credential_store(keyed=False),
                RepositoryProvider.GITHUB,
                "acme",
                "widgets",
                "https://github.com/acme/widgets.git",
                "main",
                credential="ghp_supersecrettoken",
            )
        )

    assert repository_port.created == []
    identity = asyncio.run(
        repository_port.get_by_identity(RepositoryProvider.GITHUB, "acme", "widgets")
    )
    assert identity is None


def test_register_repository_rejects_credential_for_non_github_provider() -> None:
    repository_port = _FakeCodeRepositoryRepository()

    with pytest.raises(UnsupportedCredentialProviderError):
        asyncio.run(
            register_repository(
                repository_port,
                _ExplodingCredentialStore(),
                RepositoryProvider.GITLAB,
                "acme",
                "widgets",
                "https://gitlab.com/acme/widgets.git",
                "main",
                credential="ghp_supersecrettoken",
            )
        )

    assert repository_port.created == []


def test_register_repository_without_credential_ignores_non_github_provider() -> None:
    """The GitHub-only guard only fires when a credential is actually submitted."""
    repository_port = _FakeCodeRepositoryRepository()

    created = asyncio.run(
        register_repository(
            repository_port,
            _credential_store(),
            RepositoryProvider.GITLAB,
            "acme",
            "widgets",
            "https://gitlab.com/acme/widgets.git",
            "main",
        )
    )

    assert created.credential_kind is None
    assert created.credential_ciphertext is None
