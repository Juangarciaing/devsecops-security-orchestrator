"""Unique-constraint violations raise `IntegrityError` on real insert against
a live Postgres (spec scenarios).

DDL-level uniqueness was already verified against SQLite metadata in PR3's
`test_models_metadata.py`; these tests prove the constraints are actually
enforced at insert time.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError
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


async def _duplicate_scan_task_scanner_type() -> None:
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

            session.add(ScanTaskModel(scan_run_id=scan_run.id, scanner_type=ScannerType.SAST))
            await session.commit()

            scan_run_id = scan_run.id

        async with sessionmaker() as session:
            session.add(ScanTaskModel(scan_run_id=scan_run_id, scanner_type=ScannerType.SAST))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


async def _duplicate_finding_fingerprint() -> None:
    """Module 7 PR2: dedup moved from `UNIQUE(scan_task_id, fingerprint)` to
    `UNIQUE(repository_id, fingerprint)` — proves the SAME repository, a
    DIFFERENT scan_task, and the SAME fingerprint now collide (which the old
    per-scan-task constraint would have allowed)."""
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

            scan_task_1 = ScanTaskModel(scan_run_id=scan_run.id, scanner_type=ScannerType.SAST)
            session.add(scan_task_1)
            await session.flush()

            session.add(
                FindingModel(
                    scan_task_id=scan_task_1.id,
                    repository_id=repository.id,
                    severity=FindingSeverity.HIGH,
                    rule_id="rule-1",
                    title="Hardcoded secret",
                    fingerprint="fp-1",
                )
            )
            await session.commit()

            repository_id = repository.id
            scan_run_id = scan_run.id

        async with sessionmaker() as session:
            # A different scan_task (same scan_run, different scanner_type)
            # belonging to the SAME repository.
            scan_task_2 = ScanTaskModel(scan_run_id=scan_run_id, scanner_type=ScannerType.SECRETS)
            session.add(scan_task_2)
            await session.flush()

            session.add(
                FindingModel(
                    scan_task_id=scan_task_2.id,
                    repository_id=repository_id,
                    severity=FindingSeverity.HIGH,
                    rule_id="rule-2",
                    title="Duplicate fingerprint",
                    fingerprint="fp-1",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


def test_duplicate_scan_run_scanner_type_raises_integrity_error(migrated_schema: None) -> None:
    asyncio.run(_duplicate_scan_task_scanner_type())


def test_duplicate_scan_task_fingerprint_raises_integrity_error(migrated_schema: None) -> None:
    asyncio.run(_duplicate_finding_fingerprint())


async def _duplicate_user_email() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            session.add(UserModel(email="dup@example.com", hashed_password="hashed"))
            await session.commit()

        async with sessionmaker() as session:
            session.add(UserModel(email="dup@example.com", hashed_password="other-hash"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


async def _duplicate_api_key_prefix() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            user = UserModel(email="key-owner@example.com", hashed_password="hashed")
            session.add(user)
            await session.flush()

            session.add(
                ApiKeyModel(user_id=user.id, key_prefix="dso_dup12345", hashed_key="hash-1")
            )
            await session.commit()

            user_id = user.id

        async with sessionmaker() as session:
            session.add(
                ApiKeyModel(user_id=user_id, key_prefix="dso_dup12345", hashed_key="hash-2")
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


def test_duplicate_user_email_raises_integrity_error(migrated_schema: None) -> None:
    asyncio.run(_duplicate_user_email())


def test_duplicate_api_key_prefix_raises_integrity_error(migrated_schema: None) -> None:
    asyncio.run(_duplicate_api_key_prefix())
