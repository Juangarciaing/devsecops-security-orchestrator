"""`GitHubCheckPublicationPort` — persistence contract for
`GitHubCheckPublication`. Framework-free: MUST NOT import SQLAlchemy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from orchestrator.domain.entities.github_check_publication import GitHubCheckPublication


class GitHubCheckPublicationPort(ABC):
    """Async persistence contract; claim/dispatch land with the repository
    behavior in PR2 — this PR only wires atomic creation."""

    @abstractmethod
    async def create(self, publication: GitHubCheckPublication) -> None:
        """Atomically persist `publication` as a new outbox row."""
