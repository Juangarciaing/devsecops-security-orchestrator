"""Pydantic v2 I/O schemas for `CodeRepository`.

Application-boundary DTOs. Mirror `domain.entities.code_repository.CodeRepository`
fields for I/O only — this is a DISTINCT layer from the ORM model, never the
same class (decision D3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.value_objects.enums import RepositoryProvider


class CodeRepositoryCreate(BaseModel):
    """Input schema for creating a `CodeRepository`.

    No `is_active` field: a newly registered repository always starts active
    (`True`), set server-side by the use case — never client-controlled.
    """

    model_config = ConfigDict(extra="forbid")

    provider: RepositoryProvider
    owner: str
    name: str
    clone_url: str
    default_branch: str
    credential_ref: str | None = None


class CodeRepositoryRead(BaseModel):
    """Output schema mirroring the full `CodeRepository` entity."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    provider: RepositoryProvider
    owner: str
    name: str
    clone_url: str
    default_branch: str
    credential_ref: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: CodeRepository) -> CodeRepositoryRead:
        """Build a `CodeRepositoryRead` from a domain `CodeRepository` entity."""
        return cls(
            id=entity.id,
            provider=entity.provider,
            owner=entity.owner,
            name=entity.name,
            clone_url=entity.clone_url,
            default_branch=entity.default_branch,
            credential_ref=entity.credential_ref,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def to_entity(self) -> CodeRepository:
        """Convert this schema back into a domain `CodeRepository` entity."""
        return CodeRepository(
            id=self.id,
            provider=self.provider,
            owner=self.owner,
            name=self.name,
            clone_url=self.clone_url,
            default_branch=self.default_branch,
            credential_ref=self.credential_ref,
            is_active=self.is_active,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class CodeRepositoryUpdate(BaseModel):
    """Input schema for partially updating a `CodeRepository`.

    Only mutable fields are accepted — identity (`provider`/`owner`/`name`)
    is immutable after creation and MUST NOT be exposed here (422 if
    supplied). All fields are optional; the use case distinguishes
    "omitted" from "explicitly set to null" via `model_fields_set`.
    """

    model_config = ConfigDict(extra="forbid")

    clone_url: str | None = None
    default_branch: str | None = None
    credential_ref: str | None = None
