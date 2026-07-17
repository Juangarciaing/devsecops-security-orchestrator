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

__all__ = [
    "ApiKeyModel",
    "CodeRepositoryModel",
    "FindingModel",
    "ScanRunModel",
    "ScanTaskModel",
    "UserModel",
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
    assert ("scan_task_id", "fingerprint") in unique_column_sets

    fks = inspector.get_foreign_keys("findings")
    assert any(
        fk["referred_table"] == "scan_tasks" and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )


def test_scan_runs_fk_cascade(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    fks = inspector.get_foreign_keys("scan_runs")
    assert any(
        fk["referred_table"] == "code_repositories" and fk["options"].get("ondelete") == "CASCADE"
        for fk in fks
    )
