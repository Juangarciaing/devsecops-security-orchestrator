"""GitHub Checks outbox persistence and migration proof against a live
Postgres (spec: Atomic Eligible Intent, Single Logical Check Run, GitHub App
Authorization and Mapping).
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.domain.value_objects.enums import (
    GitHubCheckOutcome,
    GitHubCheckPublicationStatus,
    RepositoryProvider,
)
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models import (
    CodeRepositoryModel,
    GitHubCheckPublicationModel,
    GitHubRepositoryInstallationModel,
    ScanRunModel,
)

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOWN_REVISION = "5e9b7a1c2d3e"


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    repository = CodeRepositoryModel(
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
    )
    session.add(repository)
    await session.flush()
    scan_run = ScanRunModel(
        repository_id=repository.id, trigger="push", commit_sha="abc123", ref="refs/heads/main"
    )
    session.add(scan_run)
    await session.flush()
    return repository.id, scan_run.id


def _publication(scan_run_id: uuid.UUID) -> GitHubCheckPublicationModel:
    return GitHubCheckPublicationModel(
        scan_run_id=scan_run_id,
        check_name="security/orchestrator",
        outcome=GitHubCheckOutcome.SUCCESS,
        payload_summary="0 findings",
    )


async def _outbox_lifecycle() -> None:
    """Unique `(scan_run_id, check_name)`, mapping-row uniqueness, and
    immutable intent fields; leaves rows behind for the downgrade proof."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository_id, scan_run_id = await _seed(session)
            publication = _publication(scan_run_id)
            session.add(publication)
            session.add(
                GitHubRepositoryInstallationModel(repository_id=repository_id, installation_id=1001)
            )
            await session.commit()
            publication_id, original_created_at = publication.id, publication.created_at

        async with sessionmaker() as session:
            session.add(_publication(scan_run_id))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        async with sessionmaker() as session:
            session.add(
                GitHubRepositoryInstallationModel(repository_id=repository_id, installation_id=2002)
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        async with sessionmaker() as session:
            await session.execute(
                update(GitHubCheckPublicationModel)
                .where(GitHubCheckPublicationModel.id == publication_id)
                .values(status=GitHubCheckPublicationStatus.CLAIMED)
            )
            await session.commit()

        async with sessionmaker() as session:
            refreshed = await session.get(GitHubCheckPublicationModel, publication_id)
            assert refreshed is not None
            assert refreshed.check_name == "security/orchestrator"
            assert refreshed.created_at == original_created_at
    finally:
        await engine.dispose()


async def _table_exists(table_name: str) -> bool:
    engine = create_async_engine(resolve_database_url())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT to_regclass(:q) IS NOT NULL"), {"q": f"public.{table_name}"}
            )
            return bool(result.scalar())
    finally:
        await engine.dispose()


def test_outbox_persistence_then_populated_row_safe_downgrade(db_env: None) -> None:
    """Populated `DROP TABLE` never raises, unlike an FK-guarded drop would."""
    _run_alembic("upgrade", "head")
    try:
        asyncio.run(_outbox_lifecycle())
        _run_alembic("downgrade", DOWN_REVISION)
        assert asyncio.run(_table_exists("github_check_publications")) is False
        assert asyncio.run(_table_exists("github_repository_installations")) is False
    finally:
        _run_alembic("downgrade", "base")
