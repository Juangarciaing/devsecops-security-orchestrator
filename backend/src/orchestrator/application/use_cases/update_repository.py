"""`update_repository` use case — mutable-fields-only PATCH, omitted vs explicit-null aware."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.code_repository import CodeRepositoryUpdate
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort


async def update_repository(
    repository_port: CodeRepositoryPort,
    repository_id: uuid.UUID,
    update: CodeRepositoryUpdate,
) -> CodeRepository:
    """Apply only the fields explicitly provided in `update` to an active repository.

    Uses `model_fields_set` to distinguish "omitted" (leave unchanged) from
    "explicitly set to null" (apply the null) — this matters for
    `credential_ref`, which is nullable. Identity fields are never touched;
    they are not exposed by `CodeRepositoryUpdate`.

    Raises `RepositoryNotFoundError` if `repository_id` does not exist or the
    repository is inactive (soft-deleted).
    """
    repository = await repository_port.get_by_id(repository_id)
    if repository is None or not repository.is_active:
        raise RepositoryNotFoundError(repository_id)

    fields_set = update.model_fields_set
    if "clone_url" in fields_set and update.clone_url is not None:
        repository.clone_url = update.clone_url
    if "default_branch" in fields_set and update.default_branch is not None:
        repository.default_branch = update.default_branch
    if "credential_ref" in fields_set:
        repository.credential_ref = update.credential_ref

    repository.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await repository_port.update(repository)
