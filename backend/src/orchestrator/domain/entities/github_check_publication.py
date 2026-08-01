"""GitHubCheckPublication entity — immutable intent; no SQLAlchemy/Pydantic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import GitHubCheckOutcome


@dataclass(slots=True, frozen=True)
class GitHubCheckPublication:
    """Durable, atomically-created publication intent (spec: Atomic
    Eligible Intent); lifecycle/lease columns live on the ORM model."""

    id: uuid.UUID
    scan_run_id: uuid.UUID
    check_name: str
    outcome: GitHubCheckOutcome
    payload_summary: str
    created_at: datetime
