"""Pydantic v2 I/O schemas for `Finding`.

Application-boundary DTOs. Mirror `domain.entities.finding.Finding` fields for
I/O only — this is a DISTINCT layer from the ORM model, never the same class
(decision D3). Redaction-sensitive fields (`raw_evidence`, `snippet`,
`file_path`, `line_number`) are carried through unchanged — no redaction logic
lives here (Module 3 concern).

`FindingRead` gained `repository_id`/`first_seen_scan_run_id`/
`last_seen_scan_run_id` in Module 7 PR2 (all optional, default `None`).
`FindingCreate` is intentionally left unchanged here: it has no live caller
and no test coverage yet, so extending it now would be speculative ahead of
the write path (Module 7 PR3/PR4) that will determine what a creator actually
needs to supply.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus


class FindingCreate(BaseModel):
    """Input schema for creating a `Finding`."""

    model_config = ConfigDict(extra="forbid")

    scan_task_id: uuid.UUID
    severity: FindingSeverity
    rule_id: str
    title: str
    fingerprint: str
    status: FindingStatus = FindingStatus.OPEN
    description: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    raw_evidence: dict[str, Any] | None = None
    snippet: str | None = None


class FindingRead(BaseModel):
    """Output schema mirroring the full `Finding` entity."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    scan_task_id: uuid.UUID
    severity: FindingSeverity
    status: FindingStatus
    rule_id: str
    title: str
    fingerprint: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    raw_evidence: dict[str, Any] | None = None
    snippet: str | None = None
    repository_id: uuid.UUID | None = None
    first_seen_scan_run_id: uuid.UUID | None = None
    last_seen_scan_run_id: uuid.UUID | None = None

    @classmethod
    def from_entity(cls, entity: Finding) -> FindingRead:
        """Build a `FindingRead` from a domain `Finding` entity."""
        return cls(
            id=entity.id,
            scan_task_id=entity.scan_task_id,
            severity=entity.severity,
            status=entity.status,
            rule_id=entity.rule_id,
            title=entity.title,
            fingerprint=entity.fingerprint,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            description=entity.description,
            file_path=entity.file_path,
            line_number=entity.line_number,
            raw_evidence=entity.raw_evidence,
            snippet=entity.snippet,
            repository_id=entity.repository_id,
            first_seen_scan_run_id=entity.first_seen_scan_run_id,
            last_seen_scan_run_id=entity.last_seen_scan_run_id,
        )

    def to_entity(self) -> Finding:
        """Convert this schema back into a domain `Finding` entity."""
        return Finding(
            id=self.id,
            scan_task_id=self.scan_task_id,
            severity=self.severity,
            status=self.status,
            rule_id=self.rule_id,
            title=self.title,
            fingerprint=self.fingerprint,
            created_at=self.created_at,
            updated_at=self.updated_at,
            description=self.description,
            file_path=self.file_path,
            line_number=self.line_number,
            raw_evidence=self.raw_evidence,
            snippet=self.snippet,
            repository_id=self.repository_id,
            first_seen_scan_run_id=self.first_seen_scan_run_id,
            last_seen_scan_run_id=self.last_seen_scan_run_id,
        )
