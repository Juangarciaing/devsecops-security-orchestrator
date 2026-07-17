"""`list_repositories` use case — returns only active repositories."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.list_repositories import list_repositories
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
        self._repositories = repositories

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        raise NotImplementedError

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        raise NotImplementedError

    async def list_all(self) -> list[CodeRepository]:
        return list(self._repositories)

    async def list_active(self) -> list[CodeRepository]:
        return [repo for repo in self._repositories if repo.is_active]

    async def create(self, repository: CodeRepository) -> CodeRepository:
        raise NotImplementedError

    async def update(self, repository: CodeRepository) -> CodeRepository:
        raise NotImplementedError

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError

    async def delete(self, repository_id: uuid.UUID) -> None:
        raise NotImplementedError


def test_list_repositories_returns_only_active() -> None:
    active = _make_repository(name="active-repo")
    inactive = _make_repository(name="inactive-repo", is_active=False)
    repository_port = _FakeCodeRepositoryRepository([active, inactive])

    result = asyncio.run(list_repositories(repository_port))

    assert result == [active]


def test_list_repositories_returns_empty_when_none_active() -> None:
    inactive = _make_repository(name="inactive-only", is_active=False)
    repository_port = _FakeCodeRepositoryRepository([inactive])

    result = asyncio.run(list_repositories(repository_port))

    assert result == []
