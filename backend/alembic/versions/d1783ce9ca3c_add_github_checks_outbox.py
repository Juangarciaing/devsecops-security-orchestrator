"""add github checks outbox

Revision ID: d1783ce9ca3c
Revises: 5e9b7a1c2d3e
Create Date: 2026-08-01 14:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1783ce9ca3c"
down_revision: str | Sequence[str] | None = "5e9b7a1c2d3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "github_check_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_run_id", sa.Uuid(), nullable=False),
        sa.Column("check_name", sa.String(), nullable=False),
        sa.Column(
            "outcome", sa.Enum("SUCCESS", "FAILURE", name="github_check_outcome"), nullable=False
        ),
        sa.Column("payload_summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CLAIMED",
                "DELIVERED",
                "DEAD",
                "DISABLED",
                name="github_check_publication_status",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_github_check_publications")),
        sa.UniqueConstraint(
            "scan_run_id", "check_name", name="uq_github_check_publications_scan_check"
        ),
    )

    op.create_table(
        "github_repository_installations",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["code_repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("repository_id", name=op.f("pk_github_repository_installations")),
    )


def downgrade() -> None:
    """Downgrade schema. `DROP TABLE` is safe even with populated rows."""
    op.drop_table("github_repository_installations")
    op.drop_table("github_check_publications")
    bind = op.get_bind()
    sa.Enum(name="github_check_publication_status").drop(bind, checkfirst=True)
    sa.Enum(name="github_check_outcome").drop(bind, checkfirst=True)
