"""add repository_id and scan run tracking to findings

Revision ID: 9a4af6f0e9d0
Revises: 04c47c6921fb
Create Date: 2026-07-18 14:41:03.899435

Additive migration (Module 7 D3): denormalizes `repository_id` onto
`findings` (`ON DELETE CASCADE`) and adds `first_seen_scan_run_id`/
`last_seen_scan_run_id` (`ON DELETE SET NULL`). Dedup scope moves from
per-scan-task (`UNIQUE(scan_task_id, fingerprint)`) to per-repository
(`UNIQUE(repository_id, fingerprint)`).

Backfill (for any pre-existing rows — a fresh dev DB has none): join
`findings -> scan_tasks -> scan_runs` to resolve `repository_id`, and stamp
both `first_seen_scan_run_id`/`last_seen_scan_run_id` to that same
`scan_run_id` (there is no way to reconstruct true first/last-seen history
retroactively, so the backfill treats every existing finding as if it were
first/last seen on its one known producing run).

All 3 new columns stay `nullable=True` (deviation from design D3's literal
"`repository_id` ... NOT NULL" wording): the write path that guarantees a
value on every insert (`bulk_upsert_findings` + `process_scan_task`'s
registry re-route, D6) is Module 7 PR3/PR4 — not this PR2 migration. Until
that lands, `process_scan.py`'s existing per-finding `create()` loop has no
`repository_id` to supply, and a `NOT NULL` constraint here would break
every live-DB scan integration test before PR4 wires the value through. PR4
should add a follow-up migration enforcing `NOT NULL` once every write path
guarantees population. `UNIQUE(repository_id, fingerprint)` is safe with
nullable `repository_id`: Postgres treats every `NULL` as distinct, so
unmigrated rows never spuriously collide.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a4af6f0e9d0"
down_revision: str | Sequence[str] | None = "04c47c6921fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the 3 new columns, all nullable (see module docstring for why
    #    `repository_id` stays nullable too, not just the SET NULL pair).
    op.add_column("findings", sa.Column("repository_id", sa.Uuid(), nullable=True))
    op.add_column("findings", sa.Column("first_seen_scan_run_id", sa.Uuid(), nullable=True))
    op.add_column("findings", sa.Column("last_seen_scan_run_id", sa.Uuid(), nullable=True))

    # 2. Backfill from the existing scan_task -> scan_run join. No-op on a
    #    fresh DB with an empty `findings` table.
    op.execute(
        """
        UPDATE findings
        SET repository_id = scan_runs.repository_id,
            first_seen_scan_run_id = scan_tasks.scan_run_id,
            last_seen_scan_run_id = scan_tasks.scan_run_id
        FROM scan_tasks
        JOIN scan_runs ON scan_runs.id = scan_tasks.scan_run_id
        WHERE scan_tasks.id = findings.scan_task_id
        """
    )

    # 3. FKs: repository_id CASCADE (matches scan_runs.repository_id);
    #    first/last_seen_scan_run_id SET NULL (historical findings survive
    #    their producing ScanRun being deleted).
    op.create_foreign_key(
        op.f("fk_findings_repository_id_code_repositories"),
        "findings",
        "code_repositories",
        ["repository_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_findings_first_seen_scan_run_id_scan_runs"),
        "findings",
        "scan_runs",
        ["first_seen_scan_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_findings_last_seen_scan_run_id_scan_runs"),
        "findings",
        "scan_runs",
        ["last_seen_scan_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_findings_repository_id"), "findings", ["repository_id"], unique=False)

    # 4. Swap the unique constraint: dedup is now per-repository, not
    #    per-scan-task.
    op.drop_constraint(op.f("uq_findings_scan_task_id_fingerprint"), "findings", type_="unique")
    op.create_unique_constraint(
        op.f("uq_findings_repository_id_fingerprint"), "findings", ["repository_id", "fingerprint"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("uq_findings_repository_id_fingerprint"), "findings", type_="unique")
    op.create_unique_constraint(
        op.f("uq_findings_scan_task_id_fingerprint"), "findings", ["scan_task_id", "fingerprint"]
    )

    op.drop_index(op.f("ix_findings_repository_id"), table_name="findings")
    op.drop_constraint(
        op.f("fk_findings_last_seen_scan_run_id_scan_runs"), "findings", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_findings_first_seen_scan_run_id_scan_runs"), "findings", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_findings_repository_id_code_repositories"), "findings", type_="foreignkey"
    )

    op.drop_column("findings", "last_seen_scan_run_id")
    op.drop_column("findings", "first_seen_scan_run_id")
    op.drop_column("findings", "repository_id")
