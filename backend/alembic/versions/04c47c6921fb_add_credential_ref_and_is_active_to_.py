"""add credential_ref and is_active to code_repositories

Revision ID: 04c47c6921fb
Revises: b46d75368f19
Create Date: 2026-07-17 16:24:06.335971

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "04c47c6921fb"
down_revision: str | Sequence[str] | None = "b46d75368f19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("code_repositories", sa.Column("credential_ref", sa.String(), nullable=True))
    op.add_column(
        "code_repositories",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("code_repositories", "is_active")
    op.drop_column("code_repositories", "credential_ref")
