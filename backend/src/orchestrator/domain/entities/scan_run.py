"""ScanRun domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.domain.value_objects.scan_subject import ScanSubject


@dataclass(slots=True)
class ScanRun:
    """A single execution of the full scan pipeline against one `CodeRepository`.

    Belongs to exactly one `CodeRepository` (`repository_id`).
    """

    id: uuid.UUID
    repository_id: uuid.UUID | None
    status: ScanRunStatus
    trigger: str
    commit_sha: str | None
    ref: str | None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # The authenticated user who triggered a manual scan; `None` for a
    # webhook-triggered (`trigger="webhook"`) scan (design D8).
    triggered_by_user_id: uuid.UUID | None = None
    scan_target_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Reject incomplete or ambiguous polymorphic subjects."""
        ScanSubject.from_columns(self.repository_id, self.scan_target_id)

    @property
    def subject(self) -> ScanSubject:
        """Return the scan's exactly-one aggregate subject."""
        return ScanSubject.from_columns(self.repository_id, self.scan_target_id)
