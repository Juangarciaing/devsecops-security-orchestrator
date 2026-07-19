"""`FindingModel` ORM mapping.

Mirrors `domain.entities.finding.Finding`. Belongs to one `ScanTaskModel` via
`scan_task_id`, `ON DELETE CASCADE`. Also carries a denormalized
`repository_id` (`ON DELETE CASCADE`) so dedup can be scoped per-repository
(`UNIQUE (repository_id, fingerprint)`) instead of per-scan-task.
`first_seen_scan_run_id`/`last_seen_scan_run_id` track which `ScanRun`
first/most-recently observed this fingerprint (`ON DELETE SET NULL`).

`repository_id` is `nullable=False` (Module 7 PR3, task 4.11 — tightened from
PR2's temporary `nullable=True`): `bulk_upsert_findings` (`FindingPort`,
`SqlAlchemyFindingRepository`) is now the write path and always stamps it on
every insert, so the column-level guarantee finally matches design D3's
literal wording. See `alembic/versions/072bb3e01833_tighten_findings_repository_id_to_not_.py`
for the tightening migration (safe: PR2's own migration already backfills
`repository_id` for any pre-existing rows, and the `findings` table carries
no production data).

`first_seen_scan_run_id`/`last_seen_scan_run_id` stay `nullable=True` — a
`NOT NULL` column combined with `ON DELETE SET NULL` would raise an
`IntegrityError` the moment a referenced `ScanRun` is deleted (e.g. via the
`code_repositories -> scan_runs` cascade in `test_cascade_delete.py`).
`UNIQUE (repository_id, fingerprint)` is unaffected by any of this.

`raw_evidence` is `JSONB` (Postgres) — falls back to generic `JSON` on
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
    __table_args__ = (UniqueConstraint("repository_id", "fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_seen_scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="SET NULL"), nullable=True
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
