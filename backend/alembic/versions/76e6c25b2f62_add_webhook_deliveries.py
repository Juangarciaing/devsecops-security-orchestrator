"""add webhook deliveries

Revision ID: 76e6c25b2f62
Revises: 072bb3e01833
Create Date: 2026-07-19 13:56:20.817058

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "76e6c25b2f62"
down_revision: str | Sequence[str] | None = "072bb3e01833"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=True),
        sa.Column("source_ip", sa.String(), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "ACCEPTED",
                "DUPLICATE",
                "REJECTED_SIGNATURE",
                "IGNORED_EVENT",
                "INVALID_PAYLOAD",
                "IGNORED_UNKNOWN_REPO",
                "IGNORED_INACTIVE_REPO",
                "IGNORED_NON_DEFAULT_BRANCH",
                name="webhook_outcome",
            ),
            nullable=False,
        ),
        sa.Column("repository_full_name", sa.String(), nullable=True),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint("delivery_id", name=op.f("uq_webhook_deliveries_delivery_id")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("webhook_deliveries")
    # Manually added: see baseline migration's identical comment — autogenerate
    # does not emit the matching `DROP TYPE` for native Postgres enums.
    bind = op.get_bind()
    sa.Enum(name="webhook_outcome").drop(bind, checkfirst=True)
