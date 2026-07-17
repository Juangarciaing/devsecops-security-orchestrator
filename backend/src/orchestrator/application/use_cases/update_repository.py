"""`update_repository` use case — mutable-fields-only PATCH, omitted vs explicit-null aware."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.code_repository import CodeRepositoryUpdate
from orchestrator.application.use_cases.get_repository import RepositoryNotFoundError
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort


class InvalidRepositoryUpdateError(Exception):
    """Raised when `update` explicitly sets a non-nullable field to `null`.

    `clone_url` and `default_branch` are NOT NULL on the `CodeRepository`
    entity — an explicit `null` for either is an invalid request, not a
    legitimate "clear this field" request (unlike `credential_ref`, which is
    genuinely nullable).
    """


async def update_repository(
    repository_port: CodeRepositoryPort,
    repository_id: uuid.UUID,
    update: CodeRepositoryUpdate,
) -> CodeRepository:
    """Apply only the fields explicitly provided in `update` to an active repository.

    Uses `model_fields_set` to distinguish "omitted" (leave unchanged) from
    "explicitly set to null" (apply the null, or reject if the field isn't
    nullable) — this matters for `credential_ref`, which is nullable.
    Identity fields are never touched; they are not exposed by
    `CodeRepositoryUpdate`.

    Raises `InvalidRepositoryUpdateError` if `clone_url` or `default_branch`
    is explicitly set to `null` — both are NOT NULL on the entity, so an
    explicit null is a malformed request, not a "clear this field" request.

    Raises `RepositoryNotFoundError` if `repository_id` does not exist or the
    repository is inactive (soft-deleted).
    """
    fields_set = update.model_fields_set
    if "clone_url" in fields_set and update.clone_url is None:
        raise InvalidRepositoryUpdateError("clone_url cannot be null")
    if "default_branch" in fields_set and update.default_branch is None:
        raise InvalidRepositoryUpdateError("default_branch cannot be null")

    repository = await repository_port.get_by_id(repository_id)
    if repository is None or not repository.is_active:
        raise RepositoryNotFoundError(repository_id)

    if "clone_url" in fields_set:
        repository.clone_url = update.clone_url  # type: ignore[assignment]
    if "default_branch" in fields_set:
        repository.default_branch = update.default_branch  # type: ignore[assignment]
    if "credential_ref" in fields_set:
        repository.credential_ref = update.credential_ref

    repository.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await repository_port.update(repository)
