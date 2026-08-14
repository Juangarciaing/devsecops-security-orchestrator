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
    external_id: str | None = None
    check_run_id: int | None = None
    #: PR6 (design: "Dead-letter + replay") — total delivery attempts made
    #: so far; preserved across a protected replay for observability.
    attempt_count: int = 0
    #: Set only on a terminal `DEAD`/`DISABLED` transition; cleared by replay.
    dead_letter_reason: str | None = None
