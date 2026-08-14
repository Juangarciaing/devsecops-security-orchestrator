"""`GitHubRepositoryInstallationPort` upsert/lookup behavior against a live
Postgres (design: "App credentials"/"Tokens" — deferred from PR1/PR2 to PR5,
the persisted mapping `checks_client.py` consults before any network
discovery round-trip).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.entities.github_repository_installation import (
    GitHubRepositoryInstallation,
)
from orchestrator.domain.value_objects.enums import RepositoryProvider
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models import CodeRepositoryModel
from orchestrator.infrastructure.db.repositories.github_repository_installation_repository import (
    SqlAlchemyGitHubRepositoryInstallationRepository,
)

pytestmark = pytest.mark.integration


async def _seed_repository(session: AsyncSession) -> uuid.UUID:
    repository = CodeRepositoryModel(
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
    )
    session.add(repository)
    await session.flush()
    return repository.id


async def _upsert_lifecycle() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository_id = await _seed_repository(session)
            await session.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyGitHubRepositoryInstallationRepository(session)

            assert await repo.get_by_repository_id(repository_id) is None

            await repo.upsert(
                GitHubRepositoryInstallation(repository_id=repository_id, installation_id=1001)
            )
            await session.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyGitHubRepositoryInstallationRepository(session)
            mapping = await repo.get_by_repository_id(repository_id)
            assert mapping is not None
            assert mapping.installation_id == 1001

            # Re-discovery (design: "refreshed once on 403/404") replaces the
            # stale mapping in place rather than erroring on a duplicate PK.
            await repo.upsert(
                GitHubRepositoryInstallation(repository_id=repository_id, installation_id=2002)
            )
            await session.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyGitHubRepositoryInstallationRepository(session)
            refreshed = await repo.get_by_repository_id(repository_id)
            assert refreshed is not None
            assert refreshed.installation_id == 2002
    finally:
        await engine.dispose()


def test_upsert_then_refresh_replaces_the_stale_mapping(migrated_schema: None) -> None:
    asyncio.run(_upsert_lifecycle())
