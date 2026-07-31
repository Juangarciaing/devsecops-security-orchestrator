"""Pydantic v2 I/O schemas for `ScanTarget`.

Application-boundary DTOs. Mirror `domain.entities.scan_target.ScanTarget`
fields for I/O only — this is a DISTINCT layer from the ORM model, never the
same class (decision D3, same convention as `application/dto/code_repository.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.scan_target import ScanTarget


class ScanTargetCreate(BaseModel):
    """Input schema for registering a `ScanTarget`.

    No `is_active` field: a newly registered target always starts active
    (`True`), set server-side by the use case — never client-controlled.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    target_url: str


class ScanTargetRead(BaseModel):
    """Output schema mirroring the `ScanTarget` entity."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    target_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: ScanTarget) -> ScanTargetRead:
        """Build a `ScanTargetRead` from a domain `ScanTarget` entity."""
        return cls(
            id=entity.id,
            name=entity.name,
            target_url=entity.target_url,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def to_entity(self) -> ScanTarget:
        """Convert this schema back into a domain `ScanTarget` entity."""
        return ScanTarget(
            id=self.id,
            name=self.name,
            target_url=self.target_url,
            is_active=self.is_active,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ScanTargetUpdate(BaseModel):
    """Input schema for partially updating a `ScanTarget`.

    All fields are optional; the use case distinguishes "omitted" (leave
    unchanged) from "explicitly set to null" via `model_fields_set` — mirrors
    `CodeRepositoryUpdate`'s convention. `name`/`target_url` are both NOT NULL
    on the entity, so an explicit `null` for either is a malformed request.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    target_url: str | None = None
