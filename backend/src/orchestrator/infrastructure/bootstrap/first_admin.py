"""Idempotent first-admin bootstrap (D7).

Run via `python -m orchestrator.infrastructure.bootstrap.first_admin`. Reads
`FIRST_ADMIN_EMAIL`/`FIRST_ADMIN_PASSWORD` from `Settings`. Explicit one-shot
CLI, not a lifespan hook or Alembic data migration, to avoid a worker-race
(multiple replicas booting concurrently) and every-restart duplication.

`bootstrap_first_admin` is the pure, `UserPort`-driven check-and-create core:
it is a no-op (returns `None`, does not fail-fast) when `email`/`password` are
absent, and a no-op when at least one admin already exists — safe to invoke
on every deploy/restart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.user import User
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import UserRole
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.security.password_hasher import hash_password

logger = logging.getLogger(__name__)


async def bootstrap_first_admin(
    user_port: UserPort,
    *,
    email: str | None,
    password: str | None,
) -> User | None:
    """Create the first admin user iff none exists yet. Returns the created user or `None`."""
    if not email or not password:
        logger.info("first-admin bootstrap skipped: FIRST_ADMIN_EMAIL/PASSWORD not set")
        return None

    existing_users = await user_port.list_all()
    if any(user.role is UserRole.ADMIN for user in existing_users):
        logger.info("first-admin bootstrap skipped: an admin already exists")
        return None

    now = datetime.now(UTC).replace(tzinfo=None)
    admin = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    created = await user_port.create(admin)
    logger.info("first-admin bootstrap created admin user %s", created.email)
    return created


async def _run_cli() -> None:
    settings = get_settings()
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            user_port = SqlAlchemyUserRepository(session)
            created = await bootstrap_first_admin(
                user_port,
                email=settings.first_admin_email,
                password=settings.first_admin_password,
            )
            if created is not None:
                await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_cli())
