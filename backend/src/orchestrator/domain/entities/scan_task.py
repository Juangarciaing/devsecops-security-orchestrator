"""ScanTask domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus


@dataclass(slots=True)
class ScanTask:
    """A single scanner's execution within a `ScanRun`.

    Belongs to exactly one `ScanRun` (`scan_run_id`). At most one `ScanTask`
    per `scanner_type` may exist for a given `scan_run_id` — see `conflicts_with`.
    """

    id: uuid.UUID
    scan_run_id: uuid.UUID
    scanner_type: ScannerType
    status: ScanTaskStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    def conflicts_with(self, other: ScanTask) -> bool:
        """Whether `other` would duplicate this task's (scan_run_id, scanner_type)."""
        return self.scan_run_id == other.scan_run_id and self.scanner_type == other.scanner_type
