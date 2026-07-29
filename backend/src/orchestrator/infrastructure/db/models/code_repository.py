"""`CodeRepositoryModel` ORM mapping.

Mirrors `domain.entities.code_repository.CodeRepository`. See Module 2 design
ER model — identity uniqueness enforced as `UNIQUE (provider, owner, name)`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, UniqueConstraint, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.domain.value_objects.enums import CredentialKind, RepositoryProvider
from orchestrator.infrastructure.db.base import Base


class CodeRepositoryModel(Base):
    """ORM mapping for the `code_repositories` table."""

    __tablename__ = "code_repositories"
    __table_args__ = (UniqueConstraint("provider", "owner", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[RepositoryProvider] = mapped_column(
        SAEnum(RepositoryProvider, name="repository_provider", native_enum=True), nullable=False
    )
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    clone_url: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, nullable=False)
    credential_kind: Mapped[CredentialKind | None] = mapped_column(
        SAEnum(CredentialKind, name="credential_kind", native_enum=True), nullable=True
    )
    credential_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
