"""tighten findings repository_id to not null

Revision ID: 072bb3e01833
Revises: 9a4af6f0e9d0
Create Date: 2026-07-18 15:23:25.473787

Module 7 PR3, task 4.11: tightens `findings.repository_id` from PR2's
temporary `nullable=True` to `NOT NULL`, now that `bulk_upsert_findings`
(`FindingPort`, `SqlAlchemyFindingRepository`, Module 7 D4) is the write path
that stamps it on every insert. `process_scan.py`'s still-legacy per-finding
`create()` loop was updated in this same PR3 batch to also stamp
`repository_id` (a minimal, non-routing compat fix — the real
registry+`bulk_upsert_findings` re-wire stays Module 7 PR4, D6), so every
current write path guarantees a value.

Backfill: re-runs the same `findings -> scan_tasks -> scan_runs` join PR2's
migration (`9a4af6f0e9d0`) used, defensively, in case any row still has a
NULL `repository_id` (idempotent/no-op for already-populated rows). In
practice the `findings` table carries no production data and this migration
was validated against an empty table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "072bb3e01833"
down_revision: str | Sequence[str] | None = "9a4af6f0e9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Defensive backfill for any row PR2's own backfill missed (no-op when
    # `repository_id` is already populated on every row).
    op.execute(
        """
        UPDATE findings
        SET repository_id = scan_runs.repository_id
        FROM scan_tasks
        JOIN scan_runs ON scan_runs.id = scan_tasks.scan_run_id
        WHERE scan_tasks.id = findings.scan_task_id
          AND findings.repository_id IS NULL
        """
    )
    op.alter_column("findings", "repository_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("findings", "repository_id", existing_type=sa.Uuid(), nullable=True)
