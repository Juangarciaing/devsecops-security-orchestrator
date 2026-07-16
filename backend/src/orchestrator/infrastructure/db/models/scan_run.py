"""`ScanRunModel` ORM mapping.

Mirrors `domain.entities.scan_run.ScanRun`. Belongs to one `CodeRepositoryModel`
via `repository_id`, `ON DELETE CASCADE`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.infrastructure.db.base import Base


class ScanRunModel(Base):
    """ORM mapping for the `scan_runs` table."""

    __tablename__ = "scan_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanRunStatus] = mapped_column(
        SAEnum(ScanRunStatus, name="scan_run_status", native_enum=True),
        nullable=False,
        default=ScanRunStatus.PENDING,
        server_default=ScanRunStatus.PENDING.name,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    ref: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
