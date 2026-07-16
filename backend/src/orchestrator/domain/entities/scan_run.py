"""ScanRun domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import ScanRunStatus


@dataclass(slots=True)
class ScanRun:
    """A single execution of the full scan pipeline against one `CodeRepository`.

    Belongs to exactly one `CodeRepository` (`repository_id`).
    """

    id: uuid.UUID
    repository_id: uuid.UUID
    status: ScanRunStatus
    trigger: str
    commit_sha: str
    ref: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
