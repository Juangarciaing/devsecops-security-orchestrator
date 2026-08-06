"""`SqlAlchemyGitHubRepositoryInstallationRepository` — concrete
`GitHubRepositoryInstallationPort` adapter, mirroring
`SqlAlchemyGitHubCheckPublicationRepository`'s shape (deferred from PR1/PR2
to PR5)."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.github_repository_installation import (
    GitHubRepositoryInstallation,
)
from orchestrator.domain.ports.github_repository_installation_port import (
    GitHubRepositoryInstallationPort,
)
from orchestrator.infrastructure.db.mappers import github_repository_installation_to_entity
from orchestrator.infrastructure.db.models.github_repository_installation import (
    GitHubRepositoryInstallationModel,
)


class SqlAlchemyGitHubRepositoryInstallationRepository(GitHubRepositoryInstallationPort):
    """`GitHubRepositoryInstallationPort` adapter backed by a SQLAlchemy
    `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_repository_id(
        self, repository_id: uuid.UUID
    ) -> GitHubRepositoryInstallation | None:
        model = await self._session.get(GitHubRepositoryInstallationModel, repository_id)
        return github_repository_installation_to_entity(model) if model is not None else None

    async def upsert(self, mapping: GitHubRepositoryInstallation) -> None:
        """Atomic Postgres `INSERT ... ON CONFLICT DO UPDATE` on the
        `repository_id` primary key — a single idempotent write covers both
        first discovery and a stale-mapping refresh, with no separate
        exists-check race."""
        stmt = insert(GitHubRepositoryInstallationModel).values(
            repository_id=mapping.repository_id, installation_id=mapping.installation_id
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[GitHubRepositoryInstallationModel.repository_id],
            set_={"installation_id": mapping.installation_id},
        )
        await self._session.execute(stmt)
        await self._session.flush()
