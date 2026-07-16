"""SQLAlchemy declarative base with a stable constraint/index naming convention.

A fixed naming convention keeps Alembic's `--autogenerate` diffs deterministic
across environments (see Module 2 design, "Async Session/Engine").
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in `infrastructure/db/models/`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
