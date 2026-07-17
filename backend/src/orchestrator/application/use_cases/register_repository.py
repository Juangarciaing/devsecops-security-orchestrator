"""`register_repository` use case — rejects duplicate identity, active or soft-deleted."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.value_objects.enums import RepositoryProvider


class DuplicateRepositoryIdentityError(Exception):
    """Raised when the `(provider, owner, name)` identity already exists, active or not."""


async def register_repository(
    repository_port: CodeRepositoryPort,
    provider: RepositoryProvider,
    owner: str,
    name: str,
    clone_url: str,
    default_branch: str,
    credential_ref: str | None = None,
) -> CodeRepository:
    """Create and persist a new `CodeRepository`, always starting `is_active=True`.

    Raises `DuplicateRepositoryIdentityError` if the identity already exists,
    whether the existing match is active or soft-deleted — reactivation is
    out of scope for this module.
    """
    existing = await repository_port.get_by_identity(provider, owner, name)
    if existing is not None:
        raise DuplicateRepositoryIdentityError(f"{provider.value}/{owner}/{name}")

    now = datetime.now(UTC).replace(tzinfo=None)
    repository = CodeRepository(
        id=uuid.uuid4(),
        provider=provider,
        owner=owner,
        name=name,
        clone_url=clone_url,
        default_branch=default_branch,
        credential_ref=credential_ref,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    return await repository_port.create(repository)
