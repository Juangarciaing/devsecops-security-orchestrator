"""`SqlAlchemyCodeRepositoryRepository` — first concrete `CodeRepositoryPort`
adapter, following the pattern established by `SqlAlchemyUserRepository`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.value_objects.enums import RepositoryProvider
from orchestrator.infrastructure.db.mappers import (
    code_repository_to_entity,
    code_repository_to_model,
)
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel


class CodeRepositoryNotFoundError(LookupError):
    """Raised when a mutation targets a `CodeRepository` id that does not exist."""


class SqlAlchemyCodeRepositoryRepository(CodeRepositoryPort):
    """`CodeRepositoryPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        model = await self._session.get(CodeRepositoryModel, repository_id)
        return code_repository_to_entity(model) if model is not None else None

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        stmt = select(CodeRepositoryModel).where(
            CodeRepositoryModel.provider == provider,
            CodeRepositoryModel.owner == owner,
            CodeRepositoryModel.name == name,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return code_repository_to_entity(model) if model is not None else None

    async def list_all(self) -> list[CodeRepository]:
        stmt = select(CodeRepositoryModel)
        result = await self._session.execute(stmt)
        return [code_repository_to_entity(model) for model in result.scalars().all()]

    async def list_active(self) -> list[CodeRepository]:
        stmt = select(CodeRepositoryModel).where(CodeRepositoryModel.is_active.is_(True))
        result = await self._session.execute(stmt)
        return [code_repository_to_entity(model) for model in result.scalars().all()]

    async def create(self, repository: CodeRepository) -> CodeRepository:
        model = code_repository_to_model(repository)
        self._session.add(model)
        await self._session.flush()
        return code_repository_to_entity(model)

    async def update(self, repository: CodeRepository) -> CodeRepository:
        model = await self._session.get(CodeRepositoryModel, repository.id)
        if model is None:
            raise CodeRepositoryNotFoundError(repository.id)
        model.clone_url = repository.clone_url
        model.default_branch = repository.default_branch
        model.credential_ref = repository.credential_ref
        # Naive UTC: matches `created_at`'s `func.now()` server_default convention.
        model.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()
        return code_repository_to_entity(model)

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        model = await self._session.get(CodeRepositoryModel, repository_id)
        if model is None:
            return
        model.is_active = False
        await self._session.flush()

    async def delete(self, repository_id: uuid.UUID) -> None:
        """Delete the `CodeRepository` with the given id (cascades to dependents).

        Unused by this module — soft-delete is the sanctioned deactivation
        path (see `soft_delete`). Kept for future cascade-delete use cases.
        """
        model = await self._session.get(CodeRepositoryModel, repository_id)
        if model is None:
            return
        await self._session.delete(model)
        await self._session.flush()
