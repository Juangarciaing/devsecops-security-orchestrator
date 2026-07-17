"""`SqlAlchemyUserRepository` — the first concrete `*Port` adapter shipped in
this project (Module 2 shipped abstract ports only). Establishes the pattern:
an `AsyncSession`-backed adapter implementing a domain `*Port` via the
`mappers.py` conversion functions, never leaking SQLAlchemy above this layer.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.infrastructure.db.mappers import user_to_entity, user_to_model
from orchestrator.infrastructure.db.models.user import UserModel


class SqlAlchemyUserRepository(UserPort):
    """`UserPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return user_to_entity(model) if model is not None else None

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return user_to_entity(model) if model is not None else None

    async def create(self, user: User) -> User:
        model = user_to_model(user)
        self._session.add(model)
        await self._session.flush()
        return user_to_entity(model)

    async def list_all(self) -> list[User]:
        stmt = select(UserModel)
        result = await self._session.execute(stmt)
        return [user_to_entity(model) for model in result.scalars().all()]
