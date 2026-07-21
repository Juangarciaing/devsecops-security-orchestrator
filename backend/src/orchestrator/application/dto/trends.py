"""Pydantic v2 I/O schemas for repository finding trends (Module 12a).

Application-boundary DTOs. `TrendPoint.introduced` and
`RepositoryTrendsRead.current_open` only ever carry EXACT counts derived from
existing columns (`Finding.first_seen_scan_run_id`/`status` +
`ScanRun.created_at`) — never an approximate/reconstructed historical
open-count series. Absent severities imply a count of 0 (only severities with
a non-zero count are present as keys), mirroring `FindingTrendBucket`'s
sparse-dict convention on the domain side.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.value_objects.enums import FindingSeverity


class TrendPoint(BaseModel):
    """One bucket in a repository's trend series — one completed `ScanRun`.

    `introduced` is the EXACT count of findings whose `first_seen_scan_run_id`
    equals `scan_run_id`, grouped by `severity`. This is never a historical
    "open as of this run" reconstruction — see `FindingPort.trend_counts_by_first_seen_run`.
    """

    model_config = ConfigDict(extra="forbid")

    scan_run_id: uuid.UUID
    occurred_at: datetime
    commit_sha: str
    introduced: dict[FindingSeverity, int]


class RepositoryTrendsRead(BaseModel):
    """Full trend response for `GET /repositories/{id}/trends`.

    `points` is ordered by `TrendPoint.occurred_at` ascending. `current_open`
    is a present-moment snapshot (`status=open`, grouped by `severity`) — NOT
    a historical series value for any past point in `points`.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: uuid.UUID
    points: list[TrendPoint]
    current_open: dict[FindingSeverity, int]
