"""GitHubCheckPublication entity — immutable intent; no SQLAlchemy/Pydantic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from orchestrator.domain.value_objects.enums import GitHubCheckOutcome, GitHubCheckPublicationStatus


@dataclass(slots=True, frozen=True)
class GitHubCheckPublication:
    """Durable publication intent (spec: Atomic Eligible Intent) plus its
    claim/lease lifecycle (PR2: repository claim/dispatch behavior)."""

    id: uuid.UUID
    scan_run_id: uuid.UUID
    check_name: str
    outcome: GitHubCheckOutcome
    payload_summary: str
    created_at: datetime
    status: GitHubCheckPublicationStatus = GitHubCheckPublicationStatus.PENDING
    lease_until: datetime | None = None
    leased_by: str | None = None
