"""`get_repository` use case — 404-equivalent for missing OR inactive repositories."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.get_repository import (
    RepositoryNotFoundError,
    get_repository,
)
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
        "credential_ref": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self, repositories: list[CodeRepository]) -> None:
        self._by_id = {repo.id: repo for repo in repositories}

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
        raise NotImplementedError

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError

    async def delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError


def test_get_repository_returns_active_repository() -> None:
    repo = _make_repository()
    repository_port = _FakeCodeRepositoryRepository([repo])

    result = asyncio.run(get_repository(repository_port, repo.id))

    assert result == repo


def test_get_repository_raises_when_missing() -> None:
    repository_port = _FakeCodeRepositoryRepository([])

    try:
        asyncio.run(get_repository(repository_port, uuid.uuid4()))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass


def test_get_repository_raises_when_inactive() -> None:
    repo = _make_repository(is_active=False)
    repository_port = _FakeCodeRepositoryRepository([repo])

    try:
        asyncio.run(get_repository(repository_port, repo.id))
        raise AssertionError("expected RepositoryNotFoundError")
    except RepositoryNotFoundError:
        pass
