"""`ScanTargetModel` ORM mapping.

Mirrors `domain.entities.scan_target.ScanTarget`. `ScanTarget` is a wholly
independent aggregate (dast-scanner PR1) — no FK to `code_repositories`.
`target_url` is the dedup key, enforced as `UNIQUE (target_url)`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.infrastructure.db.base import Base


class ScanTargetModel(Base):
    """ORM mapping for the `scan_targets` table."""

    __tablename__ = "scan_targets"
    __table_args__ = (UniqueConstraint("target_url"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    target_url: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
