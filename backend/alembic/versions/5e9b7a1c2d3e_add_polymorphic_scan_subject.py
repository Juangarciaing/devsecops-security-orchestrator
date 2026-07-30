"""add polymorphic scan subject

Revision ID: 5e9b7a1c2d3e
Revises: 9afe58105f4e
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5e9b7a1c2d3e"
down_revision: str | Sequence[str] | None = "9afe58105f4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("scan_runs", "repository_id", nullable=True)
    op.alter_column("scan_runs", "commit_sha", nullable=True)
    op.alter_column("scan_runs", "ref", nullable=True)
    op.add_column("scan_runs", sa.Column("scan_target_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_scan_runs_scan_target_id",
        "scan_runs",
        "scan_targets",
        ["scan_target_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_scan_runs_exactly_one_subject",
        "scan_runs",
        "num_nonnulls(repository_id, scan_target_id) = 1",
    )
    op.alter_column("findings", "repository_id", nullable=True)
    op.add_column("findings", sa.Column("scan_target_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_findings_scan_target_id",
        "findings",
        "scan_targets",
        ["scan_target_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_findings_exactly_one_subject",
        "findings",
        "num_nonnulls(repository_id, scan_target_id) = 1",
    )
    # NULL is distinct in a plain UNIQUE constraint, so the old constraint
    # would never dedup a target-subject row once repository_id is
    # nullable. Two partial unique indexes replace it, each scoped to its
    # own non-null subject column.
    op.drop_constraint(op.f("uq_findings_repository_id_fingerprint"), "findings", type_="unique")
    op.create_index(
        "uq_findings_repository_fingerprint",
        "findings",
        ["repository_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("repository_id IS NOT NULL"),
    )
    op.create_index(
        "uq_findings_scan_target_fingerprint",
        "findings",
        ["scan_target_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("scan_target_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_findings_scan_target_fingerprint", table_name="findings")
    op.drop_index("uq_findings_repository_fingerprint", table_name="findings")
    op.create_unique_constraint(
        op.f("uq_findings_repository_id_fingerprint"),
        "findings",
        ["repository_id", "fingerprint"],
    )
    op.drop_constraint("ck_findings_exactly_one_subject", "findings", type_="check")
    op.drop_constraint("fk_findings_scan_target_id", "findings", type_="foreignkey")
    op.drop_column("findings", "scan_target_id")
    op.alter_column("findings", "repository_id", nullable=False)
    op.drop_constraint("ck_scan_runs_exactly_one_subject", "scan_runs", type_="check")
    op.drop_constraint("fk_scan_runs_scan_target_id", "scan_runs", type_="foreignkey")
    op.drop_column("scan_runs", "scan_target_id")
    op.alter_column("scan_runs", "ref", nullable=False)
    op.alter_column("scan_runs", "commit_sha", nullable=False)
    op.alter_column("scan_runs", "repository_id", nullable=False)
