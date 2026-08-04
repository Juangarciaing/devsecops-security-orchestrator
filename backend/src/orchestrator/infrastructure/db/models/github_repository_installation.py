"""`GitHubRepositoryInstallationModel` ORM mapping; `repository_id` is its
own primary key — the PK guard is the mapping-row uniqueness enforcement.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.infrastructure.db.base import Base


class GitHubRepositoryInstallationModel(Base):
    """ORM mapping for the `github_repository_installations` table."""

    __tablename__ = "github_repository_installations"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_repositories.id", ondelete="CASCADE"), primary_key=True
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
