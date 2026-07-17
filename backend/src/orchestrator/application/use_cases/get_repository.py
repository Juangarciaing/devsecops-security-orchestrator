"""`get_repository` use case — treats an inactive repository as gone (404-equivalent)."""

from __future__ import annotations

import uuid

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort


class RepositoryNotFoundError(Exception):
    """Raised when a repository id does not exist, or exists but is inactive.

    Shared across `get_repository`/`update_repository`/`deactivate_repository`
    — an inactive repository is treated as gone from the API's perspective for
    GET/PATCH, and as truly missing for DELETE only when the id never existed.
    """


async def get_repository(
    repository_port: CodeRepositoryPort, repository_id: uuid.UUID
) -> CodeRepository:
    """Return the active `CodeRepository` matching `repository_id`.

    Raises `RepositoryNotFoundError` if the id does not exist OR the
    repository is soft-deleted (`is_active=False`).
    """
    repository = await repository_port.get_by_id(repository_id)
    if repository is None or not repository.is_active:
        raise RepositoryNotFoundError(repository_id)
    return repository
