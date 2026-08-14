"""`GitHubCheckPublicationModel` ORM mapping.

`UNIQUE(scan_run_id, check_name)` backs "Single Logical Check Run" identity.
`status`/`lease_until`/`leased_by` are the lifecycle/lease/owner columns
PR2's claim repository mutates via `FOR UPDATE SKIP LOCKED` and owner-CAS
complete/release. `external_id`/`check_run_id` (PR5, design: "GitHub
identity") are model-only here — nullable-until-backfilled and unconsumed
by the domain entity/mappers until PR6 wires real delivery, mirroring PR1's
own `GitHubRepositoryInstallation` model-only deferral precedent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import GitHubCheckOutcome, GitHubCheckPublicationStatus
from orchestrator.infrastructure.db.base import Base


class GitHubCheckPublicationModel(Base):
    """ORM mapping for the `github_check_publications` table."""

    __tablename__ = "github_check_publications"
    __table_args__ = (
        UniqueConstraint(
            "scan_run_id", "check_name", name="uq_github_check_publications_scan_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False
    )
    check_name: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[GitHubCheckOutcome] = mapped_column(
        SAEnum(GitHubCheckOutcome, name="github_check_outcome", native_enum=True), nullable=False
    )
    payload_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GitHubCheckPublicationStatus] = mapped_column(
        SAEnum(
            GitHubCheckPublicationStatus, name="github_check_publication_status", native_enum=True
        ),
        nullable=False,
        default=GitHubCheckPublicationStatus.PENDING,
        server_default=GitHubCheckPublicationStatus.PENDING.name,
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leased_by: Mapped[str | None] = mapped_column(String, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    check_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: PR6 (design: "Dead-letter + replay") — total delivery attempts made;
    #: `dead_letter_reason` is set only on a terminal `DEAD` transition and
    #: cleared by a protected replay back to `PENDING`.
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    dead_letter_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
