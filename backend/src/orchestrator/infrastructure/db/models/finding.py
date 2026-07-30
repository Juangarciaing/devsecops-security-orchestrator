"""`FindingModel` ORM mapping.

Mirrors `domain.entities.finding.Finding`. Belongs to one `ScanTaskModel` via
`scan_task_id`, `ON DELETE CASCADE`. Also carries a denormalized polymorphic
subject pair, `repository_id`/`scan_target_id` (both `ON DELETE CASCADE`,
exactly one non-null — dast-scanner design D1/D2), so dedup can be scoped
per-subject instead of per-scan-task. `first_seen_scan_run_id`/
`last_seen_scan_run_id` track which `ScanRun` first/most-recently observed
this fingerprint (`ON DELETE SET NULL`).

`repository_id`/`scan_target_id` are both `nullable=True` (dast-scanner
design D1/D2 — `repository_id` was briefly tightened to `nullable=False` in
Module 7 PR3, then loosened again here to admit target-subject rows).
Because Postgres treats NULL as distinct in a plain `UNIQUE` constraint, a
single `UNIQUE (repository_id, fingerprint)` would never dedup a
target-subject row. Dedup is instead two partial unique indexes, each scoped
to its own non-null subject column — see `__table_args__` below.
`bulk_upsert_findings` (`FindingPort`, `SqlAlchemyFindingRepository`) selects
which index to conflict against based on the write's `ScanSubject.kind`.

`first_seen_scan_run_id`/`last_seen_scan_run_id` stay `nullable=True` — a
`NOT NULL` column combined with `ON DELETE SET NULL` would raise an
`IntegrityError` the moment a referenced `ScanRun` is deleted (e.g. via the
`code_repositories -> scan_runs` cascade in `test_cascade_delete.py`).

`raw_evidence` is `JSONB` (Postgres) — falls back to generic `JSON` on
SQLite so unit tests can exercise `Base.metadata.create_all` without a live DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus
from orchestrator.infrastructure.db.base import Base


class FindingModel(Base):
    """ORM mapping for the `findings` table."""

    __tablename__ = "findings"
    # Dedup key is polymorphic (design D2): `repository_id`/`scan_target_id`
    # are both nullable, so a plain `UniqueConstraint` would treat NULLs as
    # distinct and never dedup a target-subject row. Two partial unique
    # indexes, each scoped to its own non-null subject column, replace it.
    __table_args__ = (
        Index(
            "uq_findings_repository_fingerprint",
            "repository_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("repository_id IS NOT NULL"),
        ),
        Index(
            "uq_findings_scan_target_fingerprint",
            "scan_target_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("scan_target_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_repositories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scan_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=True, index=True
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
