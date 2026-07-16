"""`Base.metadata.create_all` must create all 4 tables with the expected
columns and constraints. Uses a plain sync SQLite engine — schema creation
only, no live Postgres/asyncpg required.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from orchestrator.infrastructure.db.base import Base

# Import models so they register on Base.metadata.
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel

__all__ = ["CodeRepositoryModel", "FindingModel", "ScanRunModel", "ScanTaskModel"]


@pytest.fixture
def engine() -> sa.Engine:
    eng = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_all_four_tables_are_created(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())

    assert {"code_repositories", "scan_runs", "scan_tasks", "findings"} <= table_names


def test_code_repositories_unique_constraint(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    unique_column_sets = {
        tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("code_repositories")
    }

    assert ("provider", "owner", "name") in unique_column_sets


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
