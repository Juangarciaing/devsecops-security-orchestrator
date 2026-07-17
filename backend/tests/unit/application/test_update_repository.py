"""`update_repository` use case — mutable-only, omitted-vs-null distinction, 404-on-inactive."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.code_repository import CodeRepositoryUpdate
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.application.use_cases.update_repository import update_repository
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.value_objects.enums import RepositoryProvider

_NOW = datetime.now(UTC).replace(tzinfo=None)


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_ref": "vault://secret/widgets",
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

    result = asyncio.run(update_repository(repository_port, repo.id, update))

    assert result.clone_url == "https://github.com/acme/widgets-new.git"
    # Omitted fields stay unchanged.
    assert result.default_branch == "main"
    assert result.credential_ref == "vault://secret/widgets"


def test_update_repository_distinguishes_omitted_from_explicit_null() -> None:
    repo = _make_repository(credential_ref="vault://secret/widgets")
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(credential_ref=None)

    result = asyncio.run(update_repository(repository_port, repo.id, update))

    # Explicitly set to null -> nulled, not left unchanged.
    assert result.credential_ref is None
    assert result.clone_url == "https://github.com/acme/widgets.git"


def test_update_repository_raises_when_missing() -> None:
    repository_port = _FakeCodeRepositoryRepository([])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/ghost.git")

    try:
        asyncio.run(update_repository(repository_port, uuid.uuid4(), update))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass


def test_update_repository_raises_when_inactive() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])
    update = CodeRepositoryUpdate(clone_url="https://github.com/acme/ghost.git")

    try:
        asyncio.run(update_repository(repository_port, repo.id, update))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass
