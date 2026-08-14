"""add github_check_publications.external_id and check_run_id

Revision ID: c2b7f0e14a91
Revises: 1266e9fda04b
Create Date: 2026-08-06 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2b7f0e14a91"
down_revision: str | Sequence[str] | None = "1266e9fda04b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Both columns are nullable (design: "GitHub identity")
    — `external_id` is unique but nullable-until-backfilled (mirrors PR1/
    PR2's additive-nullable precedent for existing rows); `check_run_id` is
    persisted once a POST is acknowledged, so PATCH can be used thereafter."""
    op.add_column("github_check_publications", sa.Column("external_id", sa.String(), nullable=True))
    op.add_column(
        "github_check_publications", sa.Column("check_run_id", sa.BigInteger(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_github_check_publications_external_id",
        "github_check_publications",
        ["external_id"],
    )


def downgrade() -> None:
    """Downgrade schema. Populated-row-safe: `DROP COLUMN` never raises."""
    op.drop_constraint(
        "uq_github_check_publications_external_id",
        "github_check_publications",
        type_="unique",
    )
    op.drop_column("github_check_publications", "check_run_id")
    op.drop_column("github_check_publications", "external_id")
