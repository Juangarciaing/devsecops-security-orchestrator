"""Finding domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus


@dataclass(slots=True)
class Finding:
    """A single security finding produced by a `ScanTask`.

    Belongs to exactly one `ScanTask` (`scan_task_id`). `status` defaults to
    `FindingStatus.OPEN` when not explicitly specified at creation.
    """

    #: Fields considered sensitive for redaction purposes. This is a stable
    #: public contract consumed by Module 3 — no redaction logic lives here.
    REDACTION_SENSITIVE_FIELDS = frozenset({"raw_evidence", "snippet", "file_path", "line_number"})

    id: uuid.UUID
    scan_task_id: uuid.UUID
    severity: FindingSeverity
    rule_id: str
    title: str
    fingerprint: str
    created_at: datetime
    updated_at: datetime
    status: FindingStatus = FindingStatus.OPEN
    description: str | None = None
    file_path: str | None = None
    line_number: int | None = None
    raw_evidence: dict[str, Any] | None = field(default=None)
    snippet: str | None = None
