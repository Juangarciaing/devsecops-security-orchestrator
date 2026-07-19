"""`Base.metadata.create_all` must create all 4 tables with the expected
columns and constraints. Uses a plain sync SQLite engine — schema creation
only, no live Postgres/asyncpg required.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from orchestrator.infrastructure.db.base import Base

# Import models so they register on Base.metadata.
from orchestrator.infrastructure.db.models.api_key import ApiKeyModel
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel
from orchestrator.infrastructure.db.models.user import UserModel
from orchestrator.infrastructure.db.models.webhook_delivery import WebhookDeliveryModel

__all__ = [
    "ApiKeyModel",
    "CodeRepositoryModel",
    "FindingModel",
    "ScanRunModel",
    "ScanTaskModel",
    "UserModel",
    "WebhookDeliveryModel",
]


@pytest.fixture
def engine() -> sa.Engine:
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_all_four_tables_are_created(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())

    assert {"code_repositories", "scan_runs", "scan_tasks", "findings"} <= table_names


def test_users_and_api_keys_tables_are_created(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())

    assert {"users", "api_keys"} <= table_names


def test_users_email_unique_constraint(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("users")
    }

    assert ("email",) in unique_column_sets


def test_api_keys_unique_constraint_fk_and_index(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("api_keys")
    }
    assert ("key_prefix",) in unique_column_sets

    fks = inspector.get_foreign_keys("api_keys")
    assert any(
        fk["referred_table"] == "users" and fk["options"].get("ondelete") == "CASCADE" for fk in fks
    )

    indexed_columns = {tuple(ix["column_names"]) for ix in inspector.get_indexes("api_keys")}
    assert ("user_id",) in indexed_columns


def test_api_keys_has_no_updated_at_column(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    column_names = {col["name"] for col in inspector.get_columns("api_keys")}

    assert "updated_at" not in column_names


def test_code_repositories_unique_constraint(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("code_repositories")
    }

    assert ("provider", "owner", "name") in unique_column_sets


def test_code_repositories_has_credential_ref_and_is_active_columns(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    columns = {col["name"]: col for col in inspector.get_columns("code_repositories")}

    assert "credential_ref" in columns
    assert columns["credential_ref"]["nullable"] is True

    assert "is_active" in columns
    assert columns["is_active"]["nullable"] is False


def test_scan_tasks_unique_constraint_and_fk(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("scan_tasks")
    }
    assert ("scan_run_id", "scanner_type") in unique_column_sets

    fks = inspector.get_foreign_keys("scan_tasks")
    assert any(
        fk["referred_table"] == "scan_runs" and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )


def test_findings_unique_constraint_and_fk(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("findings")
    }
    # `UNIQUE(scan_task_id, fingerprint)` was replaced by `UNIQUE(repository_id,
    # fingerprint)` in Module 7 PR2 — dedup is now per-repository, not per-task.
    assert ("repository_id", "fingerprint") in unique_column_sets
    assert ("scan_task_id", "fingerprint") not in unique_column_sets

    fks = inspector.get_foreign_keys("findings")
    assert any(
        fk["referred_table"] == "scan_tasks" and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )


def test_findings_has_repository_id_and_scan_run_tracking_columns(engine: sa.Engine) -> None:
    """Module 7 PR2/PR3: `repository_id` (denormalized, CASCADE) plus
    `first_seen_scan_run_id`/`last_seen_scan_run_id` (SET NULL).

    `repository_id` was `nullable=True` in PR2 (no write path guaranteed
    population yet) and is tightened to `NOT NULL` in PR3 (task 4.11) now
    that `bulk_upsert_findings` is the write path and always stamps it.
    `first_seen`/`last_seen` MUST stay nullable regardless — they're
    `ON DELETE SET NULL`, and a `NOT NULL` column can never be a `SET NULL`
    target without risking an `IntegrityError`."""
    inspector = sa.inspect(engine)
    columns = {col["name"]: col for col in inspector.get_columns("findings")}

    assert "repository_id" in columns
    assert columns["repository_id"]["nullable"] is False

    assert "first_seen_scan_run_id" in columns
    assert columns["first_seen_scan_run_id"]["nullable"] is True

    assert "last_seen_scan_run_id" in columns
    assert columns["last_seen_scan_run_id"]["nullable"] is True

    fks = inspector.get_foreign_keys("findings")
    assert any(
        fk["referred_table"] == "code_repositories"
        and fk["constrained_columns"] == ["repository_id"]
        and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )
    assert any(
        fk["referred_table"] == "scan_runs"
        and fk["constrained_columns"] == ["first_seen_scan_run_id"]
        and fk["options"].get("ondelete") == "SET NULL"
        for fk in fks
    )
    assert any(
        fk["referred_table"] == "scan_runs"
        and fk["constrained_columns"] == ["last_seen_scan_run_id"]
        and fk["options"].get("ondelete") == "SET NULL"
        for fk in fks
    )


def test_scan_runs_fk_cascade(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    fks = inspector.get_foreign_keys("scan_runs")
    assert any(
        fk["referred_table"] == "code_repositories" and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )


def test_webhook_deliveries_table_is_created(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "webhook_deliveries" in table_names


def test_webhook_deliveries_delivery_id_is_unique_and_nullable(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    columns = {col["name"]: col for col in inspector.get_columns("webhook_deliveries")}
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("webhook_deliveries")
    }

    assert "delivery_id" in columns
    assert columns["delivery_id"]["nullable"] is True
    assert ("delivery_id",) in unique_column_sets


def test_webhook_deliveries_required_columns_are_not_null(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    columns = {col["name"]: col for col in inspector.get_columns("webhook_deliveries")}

    assert columns["signature_valid"]["nullable"] is False
    assert columns["outcome"]["nullable"] is False
    assert columns["received_at"]["nullable"] is False


def test_webhook_deliveries_optional_columns_are_nullable(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    columns = {col["name"]: col for col in inspector.get_columns("webhook_deliveries")}

    for column_name in (
        "event_type",
        "source_ip",
        "repository_full_name",
        "ref",
        "commit_sha",
    ):
        assert columns[column_name]["nullable"] is True
