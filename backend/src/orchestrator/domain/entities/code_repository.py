"""CodeRepository domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import RepositoryProvider


@dataclass(slots=True)
class CodeRepository:
    """A source-control repository tracked by the orchestrator.

    Identity is the tuple `(provider, owner, name)` — `clone_url` is not part
    of identity, so two repositories that share the same provider/owner/name
    but differ only in `clone_url` are treated as an identity conflict, not
    two distinct repositories.
    """

    id: uuid.UUID
    provider: RepositoryProvider
    owner: str
    name: str
    clone_url: str
    default_branch: str
    created_at: datetime
    updated_at: datetime

    def identity(self) -> tuple[RepositoryProvider, str, str]:
        """Return the `(provider, owner, name)` identity tuple."""
        return (self.provider, self.owner, self.name)

    def same_identity_as(self, other: CodeRepository) -> bool:
        """Whether `other` shares this repository's identity, regardless of `clone_url`."""
        return self.identity() == other.identity()
