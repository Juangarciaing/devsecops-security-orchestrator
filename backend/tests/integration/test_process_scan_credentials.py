"""Live-Postgres proof for the secrets-manager PR6 worker wiring: the real
`process_scan_task` unseals a stored credential (or fails deterministically
trying to), always through `_load_and_start`/`_resolve_credential` and
never through any mocked-out double.

Proves, against a real database (mirrors `test_process_scan_task.py`'s
`FakeContainerRunner` + `MagicMock` docker-client double — the Docker layer
is not the point of this file, the DB-level ciphertext/audit guarantees
are):

- The stored `credential_ciphertext` column is NEVER the plaintext token
  (spec: "Envelope-Encrypted Credential Storage").
- Exactly ONE `CredentialAccessLog` row is appended per decrypt attempt,
  with the correct outcome (`USED` / `DECRYPT_FAILED` / `KEY_UNAVAILABLE`).
- A decrypt/key failure fails the scan with a credential-free error and
  leaves `CodeRepository.is_active` untouched (spec: "Decrypt Failure Is
  Credential-Free and Non-Deactivating").
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import (
    CredentialAccessOutcome,
    CredentialKind,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel
from orchestrator.infrastructure.db.models.credential_access_log import CredentialAccessLogModel
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    SqlAlchemyScanTaskRepository,
)
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
from tests.fakes.fake_container_runner import FakeContainerRunner

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 1, 1)  # naive: matches TZ-naive columns
_CLONE_URL = "https://example.com/acme-scan/widgets.git"
_REF = "main"
_HEAD_SHA = "deadbeef1234"
_PLAINTEXT_TOKEN = "ghp_supersecrettoken1234567890"

_CLONE_OK = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)
_REV_PARSE_OK = RunResult(exit_code=0, stdout=f"{_HEAD_SHA}\n", stderr="", timed_out=False)
_GITLEAKS_CLEAN = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)


def _seal(plaintext: str, key: str) -> str:
    return (
        FernetCredentialStore(encryption_key=key)
        .seal(plaintext, CredentialKind.PERSONAL_ACCESS_TOKEN)
        .ciphertext
    )


async def _seed_credentialed_repository(ciphertext: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a credentialed `CodeRepository` + pending `ScanRun`/`ScanTask`
    (trigger="manual", a fixed `triggered_by_user_id`). Returns
    `(task_id, repository_id)`."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    try:
        async with sessionmaker() as session:
            repository = await SqlAlchemyCodeRepositoryRepository(session).create(
                CodeRepository(
                    id=uuid.uuid4(),
                    provider=RepositoryProvider.GITHUB,
                    owner="acme-scan",
                    name=f"private-{uuid.uuid4().hex[:8]}",
                    clone_url=_CLONE_URL,
                    default_branch="main",
                    credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
                    credential_ciphertext=ciphertext,
                    is_active=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.commit()
            repository_id = repository.id

        async with sessionmaker() as session:
            run = await SqlAlchemyScanRunRepository(session).create(
                ScanRun(
                    id=uuid.uuid4(),
                    repository_id=repository_id,
                    status=ScanRunStatus.PENDING,
                    trigger="manual",
                    commit_sha=_REF,
                    ref=_REF,
                    created_at=_NOW,
                    triggered_by_user_id=user_id,
                )
            )
            await session.commit()
            run_id = run.id

        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).create(
                ScanTask(
                    id=uuid.uuid4(),
                    scan_run_id=run_id,
                    scanner_type=ScannerType.SECRETS,
                    status=ScanTaskStatus.PENDING,
                )
            )
            await session.commit()
            task_id = task.id

        return task_id, repository_id
    finally:
        await engine.dispose()


async def _load_repository_row(repository_id: uuid.UUID) -> CodeRepositoryModel:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            model = await session.get(CodeRepositoryModel, repository_id)
            assert model is not None
            return model
    finally:
        await engine.dispose()


async def _load_audit_rows(repository_id: uuid.UUID) -> list[CredentialAccessLogModel]:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            stmt = select(CredentialAccessLogModel).where(
                CredentialAccessLogModel.repository_id == repository_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _load_task(task_id: uuid.UUID) -> ScanTask:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            task = await SqlAlchemyScanTaskRepository(session).get_by_id(task_id)
            assert task is not None
            return task
    finally:
        await engine.dispose()


def _set_credential_encryption_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    if key is None:
        monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    get_settings.cache_clear()


def test_stored_ciphertext_is_never_the_plaintext_token_and_decrypt_succeeds(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 7: proves ciphertext-at-rest AND exactly one `USED` audit
    row on a successful, fully real decrypt-and-checkout attempt."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    key = Fernet.generate_key().decode("ascii")
    _set_credential_encryption_key(monkeypatch, key)
    ciphertext = _seal(_PLAINTEXT_TOKEN, key)

    task_id, repository_id = asyncio.run(_seed_credentialed_repository(ciphertext))

    stored = asyncio.run(_load_repository_row(repository_id))
    assert stored.credential_ciphertext == ciphertext
    assert stored.credential_ciphertext != _PLAINTEXT_TOKEN
    assert _PLAINTEXT_TOKEN not in stored.credential_ciphertext

    fake_runner = FakeContainerRunner()
    fake_runner.script(_CLONE_OK, _REV_PARSE_OK, _GITLEAKS_CLEAN)
    docker_client = MagicMock()

    process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    ).get()

    task = asyncio.run(_load_task(task_id))
    assert task.status == ScanTaskStatus.COMPLETED

    audit_rows = asyncio.run(_load_audit_rows(repository_id))
    assert len(audit_rows) == 1
    assert audit_rows[0].outcome == CredentialAccessOutcome.USED
    assert audit_rows[0].actor == "manual"
    assert audit_rows[0].actor_user_id is not None

    stored_after = asyncio.run(_load_repository_row(repository_id))
    assert stored_after.credential_ciphertext == ciphertext  # unchanged, still ciphertext only


def test_wrong_key_fails_the_scan_credential_free_without_deactivating(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 4: a rotated/wrong `credential_encryption_key` raises
    `CredentialUnsealError` inside the adapter -> the scan fails with a
    credential-free error, `outcome=DECRYPT_FAILED` is audited exactly once,
    and `CodeRepository.is_active` is NEVER flipped to `False`."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    sealing_key = Fernet.generate_key().decode("ascii")
    ciphertext = _seal(_PLAINTEXT_TOKEN, sealing_key)

    task_id, repository_id = asyncio.run(_seed_credentialed_repository(ciphertext))

    wrong_key = Fernet.generate_key().decode("ascii")
    _set_credential_encryption_key(monkeypatch, wrong_key)

    fake_runner = FakeContainerRunner()  # never scripted: checkout must never be attempted
    docker_client = MagicMock()

    process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    ).get()

    task = asyncio.run(_load_task(task_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert _PLAINTEXT_TOKEN not in task.error_message
    assert ciphertext not in task.error_message
    assert len(fake_runner.calls) == 0  # checkout never attempted

    audit_rows = asyncio.run(_load_audit_rows(repository_id))
    assert len(audit_rows) == 1
    assert audit_rows[0].outcome == CredentialAccessOutcome.DECRYPT_FAILED

    stored = asyncio.run(_load_repository_row(repository_id))
    assert stored.is_active is True  # spec: never auto-deactivated


def test_missing_encryption_key_fails_the_scan_and_is_distinct_from_decrypt_failed(
    migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 5: `Settings.credential_encryption_key` unset (but the
    row is still sealed) is audited as `outcome=KEY_UNAVAILABLE` — a
    DISTINCT outcome from `DECRYPT_FAILED` — and the worker process never
    crashes."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    sealing_key = Fernet.generate_key().decode("ascii")
    ciphertext = _seal(_PLAINTEXT_TOKEN, sealing_key)

    task_id, repository_id = asyncio.run(_seed_credentialed_repository(ciphertext))

    _set_credential_encryption_key(monkeypatch, None)  # unset on this worker

    fake_runner = FakeContainerRunner()  # never scripted: checkout must never be attempted
    docker_client = MagicMock()

    process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    ).get()

    task = asyncio.run(_load_task(task_id))
    assert task.status == ScanTaskStatus.FAILED
    assert task.error_message is not None
    assert _PLAINTEXT_TOKEN not in task.error_message
    assert len(fake_runner.calls) == 0

    audit_rows = asyncio.run(_load_audit_rows(repository_id))
    assert len(audit_rows) == 1
    assert audit_rows[0].outcome == CredentialAccessOutcome.KEY_UNAVAILABLE

    stored = asyncio.run(_load_repository_row(repository_id))
    assert stored.is_active is True


def test_public_repository_scan_never_touches_the_credential_audit_log(
    migrated_schema: None,
) -> None:
    """Requirement 6: a public repo (`credential_ciphertext is None`) leaves
    ZERO `CredentialAccessLog` rows — the exact same code path as before
    this PR."""
    from orchestrator.workers.tasks.process_scan import process_scan_task

    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _seed_public() -> tuple[uuid.UUID, uuid.UUID]:
        try:
            async with sessionmaker() as session:
                repository = await SqlAlchemyCodeRepositoryRepository(session).create(
                    CodeRepository(
                        id=uuid.uuid4(),
                        provider=RepositoryProvider.GITHUB,
                        owner="acme-scan",
                        name=f"public-{uuid.uuid4().hex[:8]}",
                        clone_url=_CLONE_URL,
                        default_branch="main",
                        credential_kind=None,
                        credential_ciphertext=None,
                        is_active=True,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                await session.commit()
                repository_id = repository.id

            async with sessionmaker() as session:
                run = await SqlAlchemyScanRunRepository(session).create(
                    ScanRun(
                        id=uuid.uuid4(),
                        repository_id=repository_id,
                        status=ScanRunStatus.PENDING,
                        trigger="manual",
                        commit_sha=_REF,
                        ref=_REF,
                        created_at=_NOW,
                    )
                )
                await session.commit()
                run_id = run.id

            async with sessionmaker() as session:
                task = await SqlAlchemyScanTaskRepository(session).create(
                    ScanTask(
                        id=uuid.uuid4(),
                        scan_run_id=run_id,
                        scanner_type=ScannerType.SECRETS,
                        status=ScanTaskStatus.PENDING,
                    )
                )
                await session.commit()
                return task.id, repository_id
        finally:
            await engine.dispose()

    task_id, repository_id = asyncio.run(_seed_public())

    fake_runner = FakeContainerRunner()
    fake_runner.script(_CLONE_OK, _REV_PARSE_OK, _GITLEAKS_CLEAN)
    docker_client = MagicMock()

    process_scan_task.apply(
        args=(str(task_id),),
        kwargs={"container_runner": fake_runner, "docker_client": docker_client},
    ).get()

    task = asyncio.run(_load_task(task_id))
    assert task.status == ScanTaskStatus.COMPLETED

    audit_rows = asyncio.run(_load_audit_rows(repository_id))
    assert audit_rows == []
