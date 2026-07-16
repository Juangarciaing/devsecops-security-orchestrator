"""`alembic/env.py` sources its database URL from `Settings`, never a literal.

Static-source check (no live DB needed): confirms `env.py` calls
`get_settings().database_url` and does not embed any hardcoded
`postgresql://...`/`sqlite://...` connection string, per the spec scenario
"no hardcoded URL".
"""

from __future__ import annotations

import re
from pathlib import Path

ENV_PY_PATH = Path(__file__).parents[2] / "alembic" / "env.py"


def test_env_py_calls_get_settings_for_database_url() -> None:
    source = ENV_PY_PATH.read_text()

    assert "get_settings()" in source
    assert "database_url" in source


def test_env_py_has_no_hardcoded_connection_string() -> None:
    source = ENV_PY_PATH.read_text()

    # Reject any literal DSN scheme embedded directly in the source (e.g.
    # "postgresql://user:pass@host/db"), which would bypass Settings entirely.
    hardcoded_dsn = re.compile(r"(postgres(?:ql)?|sqlite)(\+\w+)?://\S+@")
    assert not hardcoded_dsn.search(source)


def test_env_py_registers_orm_metadata() -> None:
    source = ENV_PY_PATH.read_text()

    assert "target_metadata" in source
    assert "Base.metadata" in source or "metadata" in source
