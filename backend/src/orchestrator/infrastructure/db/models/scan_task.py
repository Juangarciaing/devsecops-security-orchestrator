"""`ScanTaskModel` ORM mapping.

Mirrors `domain.entities.scan_task.ScanTask`. Belongs to one `ScanRunModel` via
`scan_run_id`, `ON DELETE CASCADE`. `UNIQUE (scan_run_id, scanner_type)` — one
task per scanner type per run.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus
from orchestrator.infrastructure.db.base import Base


class ScanTaskModel(Base):
    """ORM mapping for the `scan_tasks` table."""

    __tablename__ = "scan_tasks"
    __table_args__ = (UniqueConstraint("scan_run_id", "scanner_type"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False
    )
    scanner_type: Mapped[ScannerType] = mapped_column(
        SAEnum(ScannerType, name="scanner_type", native_enum=True), nullable=False
    )
    status: Mapped[ScanTaskStatus] = mapped_column(
        SAEnum(ScanTaskStatus, name="scan_task_status", native_enum=True),
        nullable=False,
        default=ScanTaskStatus.PENDING,
        server_default=ScanTaskStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
