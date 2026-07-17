"""`deactivate_repository` use case — idempotent soft-delete."""

from __future__ import annotations

import uuid

from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort


async def deactivate_repository(
    repository_port: CodeRepositoryPort, repository_id: uuid.UUID
) -> None:
    """Soft-delete the `CodeRepository` matching `repository_id`.

    Raises `RepositoryNotFoundError` only if `repository_id` truly does not
    exist. Deactivating an already-inactive repository is an idempotent
    no-op success — it never raises.
    """
    repository = await repository_port.get_by_id(repository_id)
    if repository is None:
        raise RepositoryNotFoundError(repository_id)
    await repository_port.soft_delete(repository_id)
