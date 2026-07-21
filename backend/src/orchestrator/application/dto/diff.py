"""Pydantic v2 I/O schemas for the repository scan diff (Module 12b).

Application-boundary DTOs. Unlike `dto/trends.py` (aggregate counts only, no
redaction), `RepositoryDiffRead.added`/`resolved`/`carried` carry full
per-finding bodies (`FindingRead`) that MUST already have
`redact_finding_for_role` applied by the use case before being wrapped here —
this module performs no redaction itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.application.dto.finding import FindingRead


class RunRef(BaseModel):
    """A minimal reference to one `ScanRun` — just enough to identify and
    display it (id, when it ran, and the commit it scanned)."""

    model_config = ConfigDict(extra="forbid")

    scan_run_id: uuid.UUID
    occurred_at: datetime
    commit_sha: str


class RepositoryDiffRead(BaseModel):
    """Full diff response for `GET /repositories/{id}/diff`.

    `latest_run` is `None` only when the repository has zero completed scan
    runs. `baseline_run` is `None` when fewer than 2 completed runs exist
    (insufficient history) — in that case `resolved`/`carried` are always
    empty and `added` contains every finding introduced by the sole run, if
    any (design D4).
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: uuid.UUID
    latest_run: RunRef | None
    baseline_run: RunRef | None
    added: list[FindingRead]
    resolved: list[FindingRead]
    carried: list[FindingRead]
