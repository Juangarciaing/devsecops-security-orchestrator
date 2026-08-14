"""add github_check_publication attempt_count and dead_letter_reason

Revision ID: d5394275ff73
Revises: c2b7f0e14a91
Create Date: 2026-08-13 18:02:52.842423

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5394275ff73"
down_revision: str | Sequence[str] | None = "c2b7f0e14a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema (PR6, design: "Dead-letter + replay"). `attempt_count`
    is `NOT NULL DEFAULT 0` via `server_default` so existing rows backfill
    safely; `dead_letter_reason` is nullable-until-set, mirroring PR1/PR2/
    PR5's additive-nullable precedent."""
    op.add_column(
        "github_check_publications",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "github_check_publications", sa.Column("dead_letter_reason", sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema. Populated-row-safe: `DROP COLUMN` never raises."""
    op.drop_column("github_check_publications", "dead_letter_reason")
    op.drop_column("github_check_publications", "attempt_count")
