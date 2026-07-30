"""add scan targets

Revision ID: 9afe58105f4e
Revises: a1f3c9d0e7b2
Create Date: 2026-07-30 12:19:26.181187

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9afe58105f4e"
down_revision: str | Sequence[str] | None = "a1f3c9d0e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    `ScanTarget` is a wholly independent aggregate (dast-scanner PR1, design
    D1 / proposal D1-Option B) — no FK to `code_repositories`, no linkage of
    any kind in this slice. `target_url` is the natural dedup key, so it is
    UNIQUE (design: "GREEN: create infrastructure/db/models/scan_target.py
    (scan_targets table, UNIQUE(target_url))").
    """
    op.create_table(
        "scan_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_targets")),
        sa.UniqueConstraint("target_url", name=op.f("uq_scan_targets_target_url")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scan_targets")
