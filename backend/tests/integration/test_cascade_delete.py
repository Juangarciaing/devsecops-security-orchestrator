"""Deleting a `CodeRepositoryModel` cascades through `ScanRunModel` ->
`ScanTaskModel` -> `FindingModel` (spec scenario).

DDL-level `ON DELETE CASCADE` presence was already verified against SQLite
metadata in PR3's `test_models_metadata.py`; this test proves the cascade
actually fires on a real delete against a live Postgres.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.value_objects.enums import FindingSeverity, RepositoryProvider, ScannerType
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models import (
    ApiKeyModel,
    CodeRepositoryModel,
    FindingModel,
    ScanRunModel,
    ScanTaskModel,
    UserModel,
)

pytestmark = pytest.mark.integration


async def _run() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
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
                repository_id=repository.id,
                trigger="push",
                commit_sha="abc123",
                ref="refs/heads/main",
            )
            session.add(scan_run)
            await session.flush()

            scan_task = ScanTaskModel(scan_run_id=scan_run.id, scanner_type=ScannerType.SAST)
            session.add(scan_task)
            await session.flush()

            finding = FindingModel(
                scan_task_id=scan_task.id,
                severity=FindingSeverity.HIGH,
                rule_id="rule-1",
                title="Hardcoded secret",
                fingerprint="fp-1",
            )
            session.add(finding)
            await session.commit()

            repository_id = repository.id
            scan_run_id = scan_run.id
            scan_task_id = scan_task.id
            finding_id = finding.id

        async with sessionmaker() as session:
            persisted_repository = await session.get(CodeRepositoryModel, repository_id)
            assert persisted_repository is not None
            await session.delete(persisted_repository)
            await session.commit()

        async with sessionmaker() as session:
            assert await session.get(ScanRunModel, scan_run_id) is None
            assert await session.get(ScanTaskModel, scan_task_id) is None
            assert await session.get(FindingModel, finding_id) is None
    finally:
        await engine.dispose()


def test_deleting_code_repository_cascades_to_scan_runs_tasks_and_findings(
    migrated_schema: None,
) -> None:
    asyncio.run(_run())


async def _run_user_cascade() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            user = UserModel(email="cascade@example.com", hashed_password="hashed")
            session.add(user)
            await session.flush()

            api_key = ApiKeyModel(
                user_id=user.id, key_prefix="dso_cascade1", hashed_key="hashed-secret"
            )
            session.add(api_key)
            await session.commit()

            user_id = user.id
            api_key_id = api_key.id

        async with sessionmaker() as session:
            persisted_user = await session.get(UserModel, user_id)
            assert persisted_user is not None
            await session.delete(persisted_user)
            await session.commit()

        async with sessionmaker() as session:
            assert await session.get(ApiKeyModel, api_key_id) is None
    finally:
        await engine.dispose()


def test_deleting_user_cascades_to_api_keys(migrated_schema: None) -> None:
    asyncio.run(_run_user_cascade())
