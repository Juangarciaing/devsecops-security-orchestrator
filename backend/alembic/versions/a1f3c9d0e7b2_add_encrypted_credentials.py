"""add encrypted credentials

Revision ID: a1f3c9d0e7b2
Revises: 2d367959d214
Create Date: 2026-07-29 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f3c9d0e7b2"
down_revision: str | Sequence[str] | None = "2d367959d214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `create_type=False` is only recognized by the Postgres-specific `ENUM`
# (`sqlalchemy.dialects.postgresql.ENUM`), not the generic `sa.Enum` — the
# generic type silently drops unknown kwargs, which is why an earlier
# revision of this migration kept re-attempting `CREATE TYPE` for a type it
# had already created. Both native enum types are created once, explicitly,
# below; `create_type=False` here means neither `add_column` nor
# `create_table` will ever try to create them a second time.
_CREDENTIAL_KIND_ENUM = PGEnum("PERSONAL_ACCESS_TOKEN", name="credential_kind", create_type=False)
_CREDENTIAL_ACCESS_OUTCOME_ENUM = PGEnum(
    "SEALED",
    "USED",
    "DECRYPT_FAILED",
    "KEY_UNAVAILABLE",
    name="credential_access_outcome",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema.

    Drops the old inert `credential_ref` column entirely (design decision:
    NOT repurposed as the ciphertext column — a column that could hold
    either plaintext or ciphertext has no way to tell the two apart) and
    replaces it with a `credential_kind` discriminator + opaque
    `credential_ciphertext` payload. Any pre-existing non-null legacy value
    is nulled out first — it was never encrypted and is unusable going
    forward, not migrated in place.

    Both native enum types are created explicitly, once, before anything
    references them — `credential_kind` is used both by `add_column` below
    and by `credential_access_log.credential_kind` in `create_table`, and
    `create_type=False` on the Postgres-specific `ENUM` objects (imported
    from `sqlalchemy.dialects.postgresql`, not the generic `sa.Enum`, which
    silently ignores that kwarg) means neither operation attempts its own
    `CREATE TYPE` for a type this migration already created.
    """
    _CREDENTIAL_KIND_ENUM.create(op.get_bind(), checkfirst=False)
    _CREDENTIAL_ACCESS_OUTCOME_ENUM.create(op.get_bind(), checkfirst=False)

    op.add_column(
        "code_repositories", sa.Column("credential_kind", _CREDENTIAL_KIND_ENUM, nullable=True)
    )
    op.add_column("code_repositories", sa.Column("credential_ciphertext", sa.Text(), nullable=True))
    op.execute("UPDATE code_repositories SET credential_ref = NULL")
    op.drop_column("code_repositories", "credential_ref")

    op.add_column("scan_runs", sa.Column("triggered_by_user_id", sa.Uuid(), nullable=True))

    op.create_table(
        "credential_access_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("scan_task_id", sa.Uuid(), nullable=True),
        sa.Column("credential_kind", _CREDENTIAL_KIND_ENUM, nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", _CREDENTIAL_ACCESS_OUTCOME_ENUM, nullable=False),
        sa.Column("accessed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential_access_log")),
    )
    op.create_index(
        op.f("ix_credential_access_log_repository_id"),
        "credential_access_log",
        ["repository_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_credential_access_log_repository_id"), table_name="credential_access_log"
    )
    op.drop_table("credential_access_log")

    op.drop_column("scan_runs", "triggered_by_user_id")

    op.drop_column("code_repositories", "credential_ciphertext")
    op.drop_column("code_repositories", "credential_kind")
    op.add_column("code_repositories", sa.Column("credential_ref", sa.String(), nullable=True))

    # Manually added: see the `webhook_deliveries` migration's identical
    # comment — autogenerate does not emit the matching `DROP TYPE` for
    # native Postgres enums. Raw SQL, matching the raw `CREATE TYPE` above.
    op.execute("DROP TYPE credential_kind")
    op.execute("DROP TYPE credential_access_outcome")
