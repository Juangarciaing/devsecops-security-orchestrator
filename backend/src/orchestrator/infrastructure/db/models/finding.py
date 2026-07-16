"""`FindingModel` ORM mapping.

Mirrors `domain.entities.finding.Finding`. Belongs to one `ScanTaskModel` via
`scan_task_id`, `ON DELETE CASCADE`. `UNIQUE (scan_task_id, fingerprint)` for
dedup. `raw_evidence` is `JSONB` (Postgres) — falls back to generic `JSON` on
SQLite so unit tests can exercise `Base.metadata.create_all` without a live DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus
from orchestrator.infrastructure.db.base import Base


class FindingModel(Base):
    """ORM mapping for the `findings` table."""

    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("scan_task_id", "fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        SAEnum(FindingSeverity, name="finding_severity", native_enum=True),
        nullable=False,
        index=True,
    )
    status: Mapped[FindingStatus] = mapped_column(
        SAEnum(FindingStatus, name="finding_status", native_enum=True),
        nullable=False,
        default=FindingStatus.OPEN,
        server_default=FindingStatus.OPEN.name,
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    line_number: Mapped[int | None] = mapped_column(nullable=True)
    raw_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
