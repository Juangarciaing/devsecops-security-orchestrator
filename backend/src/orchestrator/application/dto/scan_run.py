"""Pydantic v2 I/O schemas for `ScanRun`.

Application-boundary DTOs. Mirror `domain.entities.scan_run.ScanRun` fields
for I/O only — this is a DISTINCT layer from the ORM model, never the same
class (decision D3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.value_objects.enums import ScanRunStatus


class ScanRunCreate(BaseModel):
    """Input schema for creating a `ScanRun`."""

    model_config = ConfigDict(extra="forbid")

    repository_id: uuid.UUID
    status: ScanRunStatus = ScanRunStatus.PENDING
    trigger: str
    commit_sha: str
    ref: str


class ScanRunRead(BaseModel):
    """Output schema mirroring the full `ScanRun` entity."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    repository_id: uuid.UUID
    status: ScanRunStatus
    trigger: str
    commit_sha: str
    ref: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: ScanRun) -> ScanRunRead:
        """Build a `ScanRunRead` from a domain `ScanRun` entity."""
        return cls(
            id=entity.id,
            repository_id=entity.repository_id,
            status=entity.status,
            trigger=entity.trigger,
            commit_sha=entity.commit_sha,
            ref=entity.ref,
            created_at=entity.created_at,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
        )

    def to_entity(self) -> ScanRun:
        """Convert this schema back into a domain `ScanRun` entity."""
        return ScanRun(
            id=self.id,
            repository_id=self.repository_id,
            status=self.status,
            trigger=self.trigger,
            commit_sha=self.commit_sha,
            ref=self.ref,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )
