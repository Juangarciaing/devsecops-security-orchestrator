"""`GitHubRepositoryInstallationPort` — persistence contract for the GitHub
App installation-to-repository mapping (deferred from PR1/PR2 to PR5, design:
"App credentials"/"Tokens"). Framework-free: MUST NOT import SQLAlchemy."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.github_repository_installation import (
    GitHubRepositoryInstallation,
)


class GitHubRepositoryInstallationPort(ABC):
    """Async persistence contract for one repository's installation mapping."""

    @abstractmethod
    async def get_by_repository_id(
        self, repository_id: uuid.UUID
    ) -> GitHubRepositoryInstallation | None:
        """Return the persisted mapping for `repository_id`, or `None` if it
        has not yet been discovered."""

    @abstractmethod
    async def upsert(self, mapping: GitHubRepositoryInstallation) -> None:
        """Insert or replace the mapping for `mapping.repository_id` — the
        table's PK-on-`repository_id` (PR1) makes this a single idempotent
        write, used both for first discovery and for a stale-mapping
        refresh."""
