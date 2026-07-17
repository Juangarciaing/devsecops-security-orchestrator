"""`list_repositories` use case — returns only active `CodeRepository` rows."""

from __future__ import annotations

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort


async def list_repositories(repository_port: CodeRepositoryPort) -> list[CodeRepository]:
    """Return every active `CodeRepository`. No inactive-filter toggle exists."""
    return await repository_port.list_active()
