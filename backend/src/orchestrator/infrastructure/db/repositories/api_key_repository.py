"""`SqlAlchemyApiKeyRepository` — concrete `ApiKeyPort` adapter, following the
same pattern established by `SqlAlchemyUserRepository`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.ports.api_key_port import ApiKeyPort
from orchestrator.infrastructure.db.mappers import api_key_to_entity, api_key_to_model
from orchestrator.infrastructure.db.models.api_key import ApiKeyModel


class ApiKeyNotFoundError(LookupError):
    """Raised when a mutation targets an `ApiKey` id that does not exist."""


class SqlAlchemyApiKeyRepository(ApiKeyPort):
    """`ApiKeyPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, api_key: ApiKey) -> ApiKey:
        model = api_key_to_model(api_key)
        self._session.add(model)
        await self._session.flush()
        return api_key_to_entity(model)

    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        stmt = select(ApiKeyModel).where(ApiKeyModel.key_prefix == key_prefix)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return api_key_to_entity(model) if model is not None else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        stmt = select(ApiKeyModel).where(ApiKeyModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [api_key_to_entity(model) for model in result.scalars().all()]

    async def revoke(self, key_id: uuid.UUID) -> ApiKey:
        model = await self._session.get(ApiKeyModel, key_id)
        if model is None:
            raise ApiKeyNotFoundError(key_id)
        # Naive UTC: `revoked_at`/`last_used_at` are `TIMESTAMP WITHOUT TIME ZONE`
        # (Module 2 convention), matching `created_at`'s `func.now()` server_default.
        model.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()
        return api_key_to_entity(model)

    async def touch(self, key_id: uuid.UUID) -> ApiKey:
        model = await self._session.get(ApiKeyModel, key_id)
        if model is None:
            raise ApiKeyNotFoundError(key_id)
        model.last_used_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()
        return api_key_to_entity(model)
