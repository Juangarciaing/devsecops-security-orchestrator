"""Pydantic v2 I/O schemas for `ScanTask`.

Application-boundary DTOs. Mirror `domain.entities.scan_task.ScanTask` fields
for I/O only — this is a DISTINCT layer from the ORM model, never the same
class (decision D3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus


class ScanTaskCreate(BaseModel):
    """Input schema for creating a `ScanTask`."""

    model_config = ConfigDict(extra="forbid")

    scan_run_id: uuid.UUID
    scanner_type: ScannerType
    status: ScanTaskStatus = ScanTaskStatus.PENDING


class ScanTaskRead(BaseModel):
    """Output schema mirroring the full `ScanTask` entity."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    scan_run_id: uuid.UUID
    scanner_type: ScannerType
    status: ScanTaskStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def from_entity(cls, entity: ScanTask) -> ScanTaskRead:
        """Build a `ScanTaskRead` from a domain `ScanTask` entity."""
        return cls(
            id=entity.id,
            scan_run_id=entity.scan_run_id,
            scanner_type=entity.scanner_type,
            status=entity.status,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            error_message=entity.error_message,
        )

    def to_entity(self) -> ScanTask:
        """Convert this schema back into a domain `ScanTask` entity."""
        return ScanTask(
            id=self.id,
            scan_run_id=self.scan_run_id,
            scanner_type=self.scanner_type,
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            error_message=self.error_message,
        )
