"""`CodeRepositoryPort` — persistence contract for `CodeRepository`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider


class CodeRepositoryPort(ABC):
    """Async persistence contract for the `CodeRepository` aggregate."""

    @abstractmethod
    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        """Return the `CodeRepository` with the given id, or `None` if absent."""

    @abstractmethod
    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        """Return the `CodeRepository` matching the `(provider, owner, name)` identity."""

    @abstractmethod
    async def list_all(self) -> list[CodeRepository]:
        """Return every tracked `CodeRepository`."""

    @abstractmethod
    async def list_active(self) -> list[CodeRepository]:
        """Return every `CodeRepository` with `is_active=True`."""

    @abstractmethod
    async def create(self, repository: CodeRepository) -> CodeRepository:
        """Persist a new `CodeRepository` and return the stored entity."""

    @abstractmethod
    async def update(self, repository: CodeRepository) -> CodeRepository:
        """Persist mutable-field changes for an existing `CodeRepository`.

        Raises `CodeRepositoryNotFoundError` (adapter-local) if `repository.id`
        does not exist. Identity fields are never mutated by this method.
        """

    @abstractmethod
    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        """Set `is_active=False` for the given id. Idempotent: a no-op if the
        repository is already inactive or does not exist."""

    @abstractmethod
    async def delete(self, repository_id: uuid.UUID) -> None:
        """Delete the `CodeRepository` with the given id (cascades to dependents)."""
