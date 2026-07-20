"""add semgrep scanner type

Revision ID: 2d367959d214
Revises: 76e6c25b2f62
Create Date: 2026-07-20 13:02:43.236960

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d367959d214"
down_revision: str | Sequence[str] | None = "76e6c25b2f62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the `SEMGREP` label to the native Postgres `scanner_type` enum.
    Native enum labels are the uppercase member NAMES of `ScannerType`
    (SQLAlchemy's `Enum` serializes by member name, not `.value`), matching
    the existing `SAST`/`DAST`/`SCA`/`SECRETS`/`IAC` labels created in the
    baseline migration. `ADD VALUE` is additive-only and safe to run inside
    Alembic's transaction on Postgres 16 as long as the new value is not
    used in the same transaction (it is not).
    """
    op.execute("ALTER TYPE scanner_type ADD VALUE IF NOT EXISTS 'SEMGREP'")


def downgrade() -> None:
    """Downgrade schema.

    No-op: Postgres cannot drop a single value from a native enum type
    without recreating the type entirely. Leaving the unused `SEMGREP`
    label behind after a downgrade is harmless — no row can reference it
    once the application code stops emitting `ScannerType.SEMGREP`.
    """
    pass
