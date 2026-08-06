"""add github_check_publications.leased_by

Revision ID: 1266e9fda04b
Revises: d1783ce9ca3c
Create Date: 2026-08-01 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1266e9fda04b"
down_revision: str | Sequence[str] | None = "d1783ce9ca3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Nullable owner column for PR2's owner-CAS claim marks."""
    op.add_column("github_check_publications", sa.Column("leased_by", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Populated-row-safe: `DROP COLUMN` never raises."""
    op.drop_column("github_check_publications", "leased_by")
