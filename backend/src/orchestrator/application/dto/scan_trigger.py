"""Pydantic v2 I/O schemas for the trigger-scan flow.

Application-boundary DTOs, distinct from the ORM model layer (decision D3,
mirrored from `scan_run.py`/`scan_task.py`). `ScanRunDetailRead` composes a
`ScanRun` + its `ScanTask` + a findings COUNT — spec's `GET /scans/{id}`
explicitly returns a count, never a findings list (non-goal).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanRunStatus, ScanTaskStatus


class ScanTriggerRequest(BaseModel):
    """Input schema for `POST /repositories/{id}/scans`. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    commit_sha: str | None = None
    scanner_type: ScannerType | None = None


class ScanRunDetailRead(BaseModel):
    """Output schema for `GET /scans/{id}` — run + task status + findings count."""

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
    task_status: ScanTaskStatus
    findings_count: int

    @classmethod
    def from_run_task_and_count(
        cls, run: ScanRun, task: ScanTask, findings_count: int
    ) -> ScanRunDetailRead:
        """Build a `ScanRunDetailRead` from a `ScanRun`, its `ScanTask`, and a count."""
        return cls(
            id=run.id,
            repository_id=run.repository_id,
            status=run.status,
            trigger=run.trigger,
            commit_sha=run.commit_sha,
            ref=run.ref,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            task_status=task.status,
            findings_count=findings_count,
        )
