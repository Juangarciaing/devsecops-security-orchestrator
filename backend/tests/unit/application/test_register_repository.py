"""`register_repository` use case — rejects duplicate identity (active or inactive)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.register_repository import (
    DuplicateRepositoryIdentityError,
    register_repository,
)
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.value_objects.enums import RepositoryProvider

_NOW = datetime.now(UTC).replace(tzinfo=None)


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
    assert created.credential_ref is None


def test_register_repository_honors_explicit_credential_ref() -> None:
    repository_port = _FakeCodeRepositoryRepository()

    created = asyncio.run(
        register_repository(
            repository_port,
            RepositoryProvider.GITLAB,
            "acme",
            "gizmos",
            "https://gitlab.com/acme/gizmos.git",
            "develop",
            credential_ref="vault://secret/gizmos",
        )
    )

    assert created.credential_ref == "vault://secret/gizmos"
    assert created.default_branch == "develop"


def test_register_repository_raises_on_duplicate_active_identity() -> None:
    repository_port = _FakeCodeRepositoryRepository()
    asyncio.run(
        register_repository(
            repository_port,
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
