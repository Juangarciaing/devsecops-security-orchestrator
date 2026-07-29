"""`register_repository` use case — rejects duplicate identity, active or soft-deleted."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.credential_store_port import CredentialStorePort
from orchestrator.domain.value_objects.enums import CredentialKind, RepositoryProvider


class DuplicateRepositoryIdentityError(Exception):
    """Raised when the `(provider, owner, name)` identity already exists, active or not."""


class UnsupportedCredentialProviderError(Exception):
    """Raised when a credential is submitted for a repository whose provider
    is not GitHub. secrets-manager is GitHub-only by design (spec: "GitHub-
    Only Credential Scope") — checked BEFORE `seal()`/any storage access.
    """


async def register_repository(
    repository_port: CodeRepositoryPort,
    credential_store: CredentialStorePort,
    provider: RepositoryProvider,
    owner: str,
    name: str,
    clone_url: str,
    default_branch: str,
    credential: str | None = None,
) -> CodeRepository:
    """Create and persist a new `CodeRepository`, always starting `is_active=True`.

    Raises `DuplicateRepositoryIdentityError` if the identity already exists,
    whether the existing match is active or soft-deleted — reactivation is
    out of scope for this module.

    Raises `UnsupportedCredentialProviderError` if `credential` is provided
    for a non-GitHub `provider` — checked before `credential_store.seal()`
    is ever called.

    If `credential` is provided, it is sealed via `credential_store.seal()`
    BEFORE the `CodeRepository` is constructed or persisted. A failed seal
    (e.g. `CredentialSealError` — no `credential_encryption_key` configured)
    propagates out of this function before any row is written, so a failed
    registration never leaves partial state. `credential=None` reproduces
    today's behavior exactly: `credential_kind=None, credential_ciphertext=None`.
    """
    existing = await repository_port.get_by_identity(provider, owner, name)
    if existing is not None:
        raise DuplicateRepositoryIdentityError(f"{provider.value}/{owner}/{name}")

    if credential is not None and provider is not RepositoryProvider.GITHUB:
        raise UnsupportedCredentialProviderError(
            f"credentials are only supported for GitHub repositories, got {provider.value!r}"
        )

    credential_kind: CredentialKind | None = None
    credential_ciphertext: str | None = None
    if credential is not None:
        sealed = credential_store.seal(credential, CredentialKind.PERSONAL_ACCESS_TOKEN)
        credential_kind = sealed.kind
        credential_ciphertext = sealed.ciphertext

    now = datetime.now(UTC).replace(tzinfo=None)
    repository = CodeRepository(
        id=uuid.uuid4(),
        provider=provider,
        owner=owner,
        name=name,
        clone_url=clone_url,
        default_branch=default_branch,
        credential_kind=credential_kind,
        credential_ciphertext=credential_ciphertext,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    return await repository_port.create(repository)
