"""`process_scan_task` — manual phase-span coverage (Module 13a, tasks 3.1-4.10).

`run_async`/`_load_and_start`/`_checkout_and_scan`/`_complete_scan` are
monkeypatched to canned fakes for the span-shape/order tests below — these
tests exist to prove the SPAN SHAPE (names, chronological order, attributes)
`process_scan_task` emits around each phase without needing a real Postgres
or Docker socket. `test_process_scan_task.py` (integration) already covers
the real state-machine/persistence behavior end to end; duplicating that
here would be redundant.

The nesting test at the bottom calls the REAL `_checkout_and_scan` against a
mocked low-level `docker` client (same double `test_docker_container_runner.py`
and `test_git_checkout.py` already use) to prove `container.run`/`git.checkout`
spans actually nest under the `scan.checkout_and_scan` span when invoked
synchronously in the task body's thread — exactly how `process_scan_task`
calls it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import ScannerType

if TYPE_CHECKING:
    from types import ModuleType

_TASK_ID = uuid.uuid4()
_SCAN_RUN_ID = uuid.uuid4()
_REPOSITORY_ID = uuid.uuid4()
# Deliberately shaped like a credential-bearing clone URL / a real branch ref
# — the threat-matrix test below proves NEITHER ever reaches a span.
_CLONE_URL = "https://x-access-token:s3cr3t-tok3n@example.com/acme-scan/widgets.git"
_REF = "refs/heads/feature/leaky-branch"
_HEAD_SHA = "deadbeef1234"


def _fake_run_async[T](coro_factory: Callable[[AsyncSession | None], Awaitable[T]]) -> T:
    return asyncio.run(coro_factory(None))  # type: ignore[arg-type]


async def _fake_load_and_start(
    _session: AsyncSession, _scan_task_id: uuid.UUID, _settings: object
) -> tuple[str, str, uuid.UUID, uuid.UUID, ScannerType]:
    return _CLONE_URL, _REF, _SCAN_RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS


def _fake_checkout_and_scan(
    _clone_url: str,
    _ref: str,
    _scan_task_id: uuid.UUID,
    _scanner_type: ScannerType,
    _runner: object,
    _docker_client: object,
    _settings: object,
    _credential: object = None,
) -> tuple[str, list[Finding]]:
    return _HEAD_SHA, []


async def _fake_complete_scan(
    _session: AsyncSession,
    _scan_task_id: uuid.UUID,
    _scan_run_id: uuid.UUID,
    _repository_id: uuid.UUID,
    _head_sha: str,
    _findings: list[Finding],
) -> None:
    return None


def _run_task(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    from orchestrator.workers.tasks import process_scan

    monkeypatch.setattr(process_scan, "run_async", _fake_run_async)
    monkeypatch.setattr(process_scan, "_load_and_start", _fake_load_and_start)
    monkeypatch.setattr(process_scan, "_checkout_and_scan", _fake_checkout_and_scan)
    monkeypatch.setattr(process_scan, "_complete_scan", _fake_complete_scan)

    result = process_scan.process_scan_task.apply(
        args=(str(_TASK_ID),),
        kwargs={"docker_client": MagicMock()},
    )
    result.get()
    return process_scan


def test_process_scan_task_emits_a_load_and_start_span(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    names = [span.name for span in span_exporter.get_finished_spans()]
    assert "scan.load_and_start" in names


def test_process_scan_task_emits_a_checkout_and_scan_span_with_scanner_type(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert spans["scan.checkout_and_scan"].attributes is not None
    assert spans["scan.checkout_and_scan"].attributes["scanner_type"] == "secrets"


def test_checkout_and_scan_uses_the_production_execution_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orchestrator.domain.ports.scan_execution_port import ScanExecutionResult
    from orchestrator.workers.tasks import process_scan

    execution = MagicMock()
    execution.execute.return_value = ScanExecutionResult(head_sha=_HEAD_SHA, findings=[])
    monkeypatch.setattr(process_scan, "create_scan_execution", lambda *_args: execution)

    head_sha, findings = process_scan._checkout_and_scan(
        _CLONE_URL, _REF, _TASK_ID, ScannerType.SECRETS, MagicMock(), MagicMock(), MagicMock()
    )

    assert (head_sha, findings) == (_HEAD_SHA, [])
    execution.execute.assert_called_once_with(
        _CLONE_URL, _REF, _TASK_ID, ScannerType.SECRETS, credential=None
    )


def test_checkout_and_scan_threads_a_resolved_credential_into_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """secrets-manager PR6: the `Secret` resolved by `_load_and_start` is
    threaded straight through `_checkout_and_scan` into
    `ScanExecutionPort.execute(..., credential=...)` (PR5's additive param) —
    NEVER dropped on the floor."""
    from orchestrator.domain.ports.scan_execution_port import ScanExecutionResult
    from orchestrator.domain.value_objects.secret import Secret
    from orchestrator.workers.tasks import process_scan

    execution = MagicMock()
    execution.execute.return_value = ScanExecutionResult(head_sha=_HEAD_SHA, findings=[])
    monkeypatch.setattr(process_scan, "create_scan_execution", lambda *_args: execution)
    secret = Secret("ghp_supersecrettoken")

    process_scan._checkout_and_scan(
        _CLONE_URL,
        _REF,
        _TASK_ID,
        ScannerType.SECRETS,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        secret,
    )

    execution.execute.assert_called_once_with(
        _CLONE_URL, _REF, _TASK_ID, ScannerType.SECRETS, credential=secret
    )


def test_process_scan_task_emits_a_write_back_span_with_db_attributes(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    write_back_attrs = spans["scan.write_back"].attributes
    assert write_back_attrs is not None
    assert write_back_attrs["db.system"] == "postgresql"
    assert write_back_attrs["findings.count"] == 0
    assert write_back_attrs["repository.id"] == str(_REPOSITORY_ID)
    assert write_back_attrs["scan_run.id"] == str(_SCAN_RUN_ID)


def test_process_scan_task_phase_spans_occur_in_chronological_order(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    phase_names = [
        span.name for span in span_exporter.get_finished_spans() if span.name.startswith("scan.")
    ]
    assert phase_names == ["scan.load_and_start", "scan.checkout_and_scan", "scan.write_back"]


def test_no_span_ever_carries_clone_url_ref_or_raw_finding_content(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    """Threat matrix (spec/design): sensitive data in span attributes. Neither
    the resolved `clone_url` nor the VCS `ref` may ever appear as a span
    attribute key or value — allowlisted attributes are `scanner_type`,
    `db.system`, `findings.count`, `repository.id`, `scan_run.id` only."""
    _run_task(monkeypatch)

    disallowed_keys = {"clone_url", "ref"}
    finished_spans = span_exporter.get_finished_spans()
    assert finished_spans, (
        "Expected process_scan_task to emit spans for the sensitive-attribute audit"
    )
    for span in finished_spans:
        for key, value in (span.attributes or {}).items():
            assert key not in disallowed_keys
            if isinstance(value, str):
                assert _CLONE_URL not in value
                assert _REF not in value


def test_checkout_and_scan_container_and_checkout_spans_nest_under_the_task_span(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    """Tasks 4.9/4.10: `container.run` (`DockerContainerRunner`) and
    `git.checkout` (`GitCheckout`) spans nest under `scan.checkout_and_scan`
    when `_checkout_and_scan` runs synchronously in the task body's thread —
    exactly how `process_scan_task` invokes it in production."""
    from orchestrator.infrastructure.config.settings import Settings
    from orchestrator.infrastructure.container.docker_container_runner import (
        DockerContainerRunner,
    )
    from orchestrator.workers.tasks.process_scan import _checkout_and_scan

    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    docker_client = MagicMock()
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    docker_client.containers.run.return_value = container
    runner = DockerContainerRunner(client=docker_client)

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("scan.checkout_and_scan") as task_span:
        _checkout_and_scan(
            _CLONE_URL, _REF, _TASK_ID, ScannerType.SECRETS, runner, docker_client, settings
        )

    task_span_id = task_span.get_span_context().span_id
    finished = span_exporter.get_finished_spans()

    checkout_spans = [span for span in finished if span.name == "git.checkout"]
    assert len(checkout_spans) == 1
    checkout_span = checkout_spans[0]
    assert checkout_span.parent is not None
    assert checkout_span.parent.span_id == task_span_id

    container_spans = [span for span in finished if span.name == "container.run"]
    assert len(container_spans) == 3  # clone, rev-parse, gitleaks scan
    for span in container_spans:
        assert span.parent is not None

    parent_ids = {span.parent.span_id for span in container_spans if span.parent is not None}
    # The clone/rev-parse container.run spans nest under git.checkout; the
    # scanner's own container.run nests directly under scan.checkout_and_scan.
    assert checkout_span.context is not None
    assert checkout_span.context.span_id in parent_ids
    assert task_span_id in parent_ids


# ---------------------------------------------------------------------------
# `_resolve_credential` — unseal + audit classification (secrets-manager
# PR6, design D9). Unit-level: operates on fake/real ports directly, no DB
# needed — `test_process_scan_credentials.py` (integration) proves the same
# logic end to end through the real `_load_and_start`/live Postgres.
# ---------------------------------------------------------------------------


def _make_settings(*, credential_encryption_key: str | None) -> object:
    from orchestrator.infrastructure.config.settings import Settings

    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        credential_encryption_key=credential_encryption_key,
    )


def _make_credentialed_repository(**overrides: object) -> object:
    from datetime import UTC, datetime

    from orchestrator.domain.entities.code_repository import CodeRepository
    from orchestrator.domain.value_objects.enums import CredentialKind, RepositoryProvider

    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_kind": CredentialKind.PERSONAL_ACCESS_TOKEN,
        "credential_ciphertext": "sealed-ciphertext",
        "is_active": True,
        "created_at": datetime.now(UTC).replace(tzinfo=None),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


class _FakeCredentialAccessLogPort:
    """Records every `append()` call — no DB needed for this unit-level suite."""

    def __init__(self) -> None:
        self.entries: list[object] = []

    async def append(self, entry: object) -> None:
        self.entries.append(entry)


def test_resolve_credential_returns_none_for_a_public_repository_unaudited() -> None:
    """Task 6.7/requirement 6: a public repo (`credential_ciphertext is
    None`) never calls `unseal()` or appends an audit row — byte-for-byte
    the same code path as before this PR."""
    from orchestrator.domain.entities.code_repository import CodeRepository
    from orchestrator.domain.value_objects.enums import RepositoryProvider
    from orchestrator.workers.tasks.process_scan import _resolve_credential

    repository = CodeRepository(
        id=uuid.uuid4(),
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
        credential_kind=None,
        credential_ciphertext=None,
        is_active=True,
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )
    audit_log = _FakeCredentialAccessLogPort()

    class _ExplodingCredentialStore:
        def unseal(self, _sealed: object) -> object:
            raise AssertionError("unseal() must never be called for a public repository")

    secret = asyncio.run(
        _resolve_credential(
            audit_log,  # type: ignore[arg-type]
            _ExplodingCredentialStore(),  # type: ignore[arg-type]
            _make_settings(credential_encryption_key=None),  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            _TASK_ID,
            actor="manual",
            actor_user_id=None,
        )
    )

    assert secret is None
    assert audit_log.entries == []


def test_resolve_credential_appends_used_and_returns_the_secret_on_success() -> None:
    """Task 6.3: a credentialed repository unseals successfully -> exactly
    one `CredentialAccessLog` row, `outcome=USED`."""
    from cryptography.fernet import Fernet

    from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind
    from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
    from orchestrator.workers.tasks.process_scan import _resolve_credential

    key = Fernet.generate_key().decode("ascii")
    store = FernetCredentialStore(encryption_key=key)
    sealed = store.seal("ghp_supersecrettoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
    repository = _make_credentialed_repository(credential_ciphertext=sealed.ciphertext)
    audit_log = _FakeCredentialAccessLogPort()

    secret = asyncio.run(
        _resolve_credential(
            audit_log,  # type: ignore[arg-type]
            store,  # type: ignore[arg-type]
            _make_settings(credential_encryption_key=key),  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            _TASK_ID,
            actor="manual",
            actor_user_id=None,
        )
    )

    assert secret is not None
    assert secret.reveal() == "ghp_supersecrettoken"
    assert len(audit_log.entries) == 1
    assert audit_log.entries[0].outcome == CredentialAccessOutcome.USED  # type: ignore[attr-defined]


def test_resolve_credential_threads_webhook_actor_with_no_user_id() -> None:
    """Task 6.5/6.6: a webhook-triggered scan audits `actor="webhook"` with
    no `actor_user_id`."""
    from cryptography.fernet import Fernet

    from orchestrator.domain.value_objects.enums import CredentialKind
    from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
    from orchestrator.workers.tasks.process_scan import _resolve_credential

    key = Fernet.generate_key().decode("ascii")
    store = FernetCredentialStore(encryption_key=key)
    sealed = store.seal("ghp_supersecrettoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
    repository = _make_credentialed_repository(credential_ciphertext=sealed.ciphertext)
    audit_log = _FakeCredentialAccessLogPort()

    asyncio.run(
        _resolve_credential(
            audit_log,  # type: ignore[arg-type]
            store,  # type: ignore[arg-type]
            _make_settings(credential_encryption_key=key),  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            _TASK_ID,
            actor="webhook",
            actor_user_id=None,
        )
    )

    entry = audit_log.entries[0]
    assert entry.actor == "webhook"  # type: ignore[attr-defined]
    assert entry.actor_user_id is None  # type: ignore[attr-defined]


def test_resolve_credential_threads_manual_actor_and_user_id() -> None:
    """Task 6.5/6.6: a manually triggered scan audits `actor="manual"` with
    the authenticated `triggered_by_user_id` threaded through as
    `actor_user_id`."""
    from cryptography.fernet import Fernet

    from orchestrator.domain.value_objects.enums import CredentialKind
    from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
    from orchestrator.workers.tasks.process_scan import _resolve_credential

    key = Fernet.generate_key().decode("ascii")
    store = FernetCredentialStore(encryption_key=key)
    sealed = store.seal("ghp_supersecrettoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
    repository = _make_credentialed_repository(credential_ciphertext=sealed.ciphertext)
    audit_log = _FakeCredentialAccessLogPort()
    user_id = uuid.uuid4()

    asyncio.run(
        _resolve_credential(
            audit_log,  # type: ignore[arg-type]
            store,  # type: ignore[arg-type]
            _make_settings(credential_encryption_key=key),  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            _TASK_ID,
            actor="manual",
            actor_user_id=user_id,
        )
    )

    entry = audit_log.entries[0]
    assert entry.actor == "manual"  # type: ignore[attr-defined]
    assert entry.actor_user_id == user_id  # type: ignore[attr-defined]


def test_resolve_credential_appends_decrypt_failed_and_raises_credential_free() -> None:
    """Task 6.7: a wrong/rotated key raises `CredentialUnsealError` inside
    the adapter -> `_resolve_credential` appends `outcome=DECRYPT_FAILED` and
    raises `CredentialUnavailableError` with a message that never mentions
    the ciphertext, the plaintext, or the key."""
    from cryptography.fernet import Fernet

    from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind
    from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
    from orchestrator.workers.tasks.process_scan import (
        CredentialUnavailableError,
        _resolve_credential,
    )

    sealing_key = Fernet.generate_key().decode("ascii")
    sealing_store = FernetCredentialStore(encryption_key=sealing_key)
    sealed = sealing_store.seal("ghp_supersecrettoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
    repository = _make_credentialed_repository(credential_ciphertext=sealed.ciphertext)
    audit_log = _FakeCredentialAccessLogPort()

    wrong_key = Fernet.generate_key().decode("ascii")
    wrong_store = FernetCredentialStore(encryption_key=wrong_key)

    with pytest.raises(CredentialUnavailableError) as exc_info:
        asyncio.run(
            _resolve_credential(
                audit_log,  # type: ignore[arg-type]
                wrong_store,  # type: ignore[arg-type]
                _make_settings(credential_encryption_key=wrong_key),  # type: ignore[arg-type]
                repository,  # type: ignore[arg-type]
                _TASK_ID,
                actor="manual",
                actor_user_id=None,
            )
        )

    assert "ghp_supersecrettoken" not in str(exc_info.value)
    assert sealed.ciphertext not in str(exc_info.value)
    assert len(audit_log.entries) == 1
    assert audit_log.entries[0].outcome == CredentialAccessOutcome.DECRYPT_FAILED  # type: ignore[attr-defined]


def test_resolve_credential_appends_key_unavailable_without_calling_unseal() -> None:
    """Task 6.9: `Settings.credential_encryption_key` unset (but the
    repository row is still sealed) is a DISTINCT outcome from a
    wrong-key/corrupted decrypt failure — checked explicitly BEFORE
    `unseal()` is ever called (there is only one `CredentialUnsealError`
    type; the missing-key case cannot be told apart from the exception
    alone), never crashes the worker process."""
    from orchestrator.domain.value_objects.enums import CredentialAccessOutcome
    from orchestrator.workers.tasks.process_scan import (
        CredentialUnavailableError,
        _resolve_credential,
    )

    repository = _make_credentialed_repository()
    audit_log = _FakeCredentialAccessLogPort()

    class _ExplodingCredentialStore:
        def unseal(self, _sealed: object) -> object:
            raise AssertionError("unseal() must not be called when the key is unavailable")

    with pytest.raises(CredentialUnavailableError):
        asyncio.run(
            _resolve_credential(
                audit_log,  # type: ignore[arg-type]
                _ExplodingCredentialStore(),  # type: ignore[arg-type]
                _make_settings(credential_encryption_key=None),  # type: ignore[arg-type]
                repository,  # type: ignore[arg-type]
                _TASK_ID,
                actor="manual",
                actor_user_id=None,
            )
        )

    assert len(audit_log.entries) == 1
    assert audit_log.entries[0].outcome == CredentialAccessOutcome.KEY_UNAVAILABLE  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# PR7 — worker wiring for a `ScanTarget`-subject run (dast-scanner design D9,
# D5). `_load_and_start`/`_run_target_scan`/`_complete_target_scan` are
# exercised here with fakes (no DB, no Docker) — `test_process_scan_task.py`
# (integration) proves the same logic end to end through the real
# `process_scan_task.apply()`/live Postgres.
# ---------------------------------------------------------------------------


_TARGET_ID = uuid.uuid4()
_TARGET_URL = "https://public.example.com"


def _make_target_settings(*, dast_enabled: bool) -> object:
    from orchestrator.infrastructure.config.settings import Settings

    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        dast_enabled=dast_enabled,
    )


class _FakeSession:
    """Stands in for `AsyncSession` — only `.commit()` is ever awaited by
    `_load_and_start`/`_complete_target_scan` outside a repository call."""

    async def commit(self) -> None:
        return None


class _FakeTaskRepoForLoad:
    def __init__(self, task: object) -> None:
        self._task = task
        self.updates: list[object] = []

    async def get_by_id(self, scan_task_id: uuid.UUID) -> object | None:
        return self._task if scan_task_id == self._task.id else None  # type: ignore[attr-defined]

    async def update_status(
        self,
        scan_task_id: uuid.UUID,
        status: object,
        *,
        started_at: object = None,
        completed_at: object = None,
        error_message: object = None,
    ) -> object:
        self.updates.append(status)
        self._task.status = status  # type: ignore[attr-defined]
        return self._task


class _FakeRunRepoForLoad:
    def __init__(self, run: object) -> None:
        self._run = run
        self.updates: list[object] = []

    async def get_by_id(self, scan_run_id: uuid.UUID) -> object | None:
        return self._run if scan_run_id == self._run.id else None  # type: ignore[attr-defined]

    async def update_status(
        self,
        scan_run_id: uuid.UUID,
        status: object,
        *,
        started_at: object = None,
        completed_at: object = None,
    ) -> object:
        self.updates.append(status)
        self._run.status = status  # type: ignore[attr-defined]
        return self._run

    async def update_commit_sha(self, scan_run_id: uuid.UUID, commit_sha: str) -> object:
        raise AssertionError(
            "update_commit_sha must never be called for a scan-target-subject completion"
        )


class _FakeTargetRepoForLoad:
    def __init__(self, target: object | None) -> None:
        self._target = target
        self.get_by_id_calls: list[uuid.UUID] = []

    async def get_by_id(self, target_id: uuid.UUID) -> object | None:
        self.get_by_id_calls.append(target_id)
        if self._target is None:
            return None
        return self._target if target_id == self._target.id else None  # type: ignore[attr-defined]


def _make_target_entities(*, task_status: object | None = None) -> tuple[object, object, object]:
    from datetime import UTC, datetime

    from orchestrator.domain.entities.scan_run import ScanRun
    from orchestrator.domain.entities.scan_target import ScanTarget
    from orchestrator.domain.entities.scan_task import ScanTask
    from orchestrator.domain.value_objects.enums import ScanRunStatus, ScanTaskStatus

    now = datetime.now(UTC).replace(tzinfo=None)
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()

    target = ScanTarget(
        id=_TARGET_ID,
        name="acme-public-site",
        target_url=_TARGET_URL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    run = ScanRun(
        id=run_id,
        repository_id=None,
        status=ScanRunStatus.PENDING,
        trigger="manual",
        commit_sha=None,
        ref=None,
        created_at=now,
        scan_target_id=_TARGET_ID,
    )
    task = ScanTask(
        id=task_id,
        scan_run_id=run_id,
        scanner_type=ScannerType.DAST,
        status=task_status or ScanTaskStatus.PENDING,
        started_at=None,
        completed_at=None,
        error_message=None,
    )
    return target, run, task


def test_load_and_start_returns_a_target_subject_tuple_for_a_scan_target_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 7.1/7.4: a `ScanTarget`-subject run returns `target_url` where
    `clone_url` used to be, with `ref`/`repository_id`/`credential` all
    `None`, and the appended `ScanSubject` a caller dispatches on."""
    from orchestrator.domain.value_objects.enums import ScanRunStatus, ScanTaskStatus
    from orchestrator.domain.value_objects.scan_subject import ScanSubject, ScanSubjectKind
    from orchestrator.workers.tasks import process_scan

    target, run, task = _make_target_entities()
    task_repo = _FakeTaskRepoForLoad(task)
    run_repo = _FakeRunRepoForLoad(run)
    target_repo = _FakeTargetRepoForLoad(target)

    monkeypatch.setattr(process_scan, "SqlAlchemyScanTaskRepository", lambda _s: task_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanRunRepository", lambda _s: run_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanTargetRepository", lambda _s: target_repo)

    settings = _make_target_settings(dast_enabled=True)
    result = asyncio.run(
        process_scan._load_and_start(_FakeSession(), task.id, settings)  # type: ignore[arg-type]
    )

    assert len(result) == 9
    (
        target_url,
        ref,
        scan_run_id,
        repository_id,
        scanner_type,
        transitioned,
        terminal,
        credential,
        subject,
    ) = result
    assert target_url == _TARGET_URL
    assert ref is None
    assert scan_run_id == run.id
    assert repository_id is None
    assert scanner_type == ScannerType.DAST
    assert transitioned is True
    assert terminal is False
    assert credential is None
    assert subject == ScanSubject(ScanSubjectKind.SCAN_TARGET, _TARGET_ID)
    assert task_repo.updates == [ScanTaskStatus.RUNNING]
    assert run_repo.updates == [ScanRunStatus.RUNNING]


def test_load_and_start_raises_dast_disabled_error_before_touching_the_target_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 7.2/7.4 (design D9): `settings.dast_enabled=False` for a
    non-terminal target-subject run raises `DastDisabledError` BEFORE the
    `ScanTargetPort` is ever called and BEFORE any `pending -> running`
    transition — the earliest possible fail-closed point, guaranteeing zero
    downstream container/network/Docker interaction."""
    from orchestrator.workers.tasks import process_scan

    target, run, task = _make_target_entities()
    task_repo = _FakeTaskRepoForLoad(task)
    run_repo = _FakeRunRepoForLoad(run)
    target_repo = _FakeTargetRepoForLoad(target)

    monkeypatch.setattr(process_scan, "SqlAlchemyScanTaskRepository", lambda _s: task_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanRunRepository", lambda _s: run_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanTargetRepository", lambda _s: target_repo)

    settings = _make_target_settings(dast_enabled=False)

    with pytest.raises(process_scan.DastDisabledError):
        asyncio.run(
            process_scan._load_and_start(_FakeSession(), task.id, settings)  # type: ignore[arg-type]
        )

    assert target_repo.get_by_id_calls == []
    assert task_repo.updates == []
    assert run_repo.updates == []


def test_load_and_start_raises_scan_target_not_found_error_for_a_missing_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 7.1: reuses `get_scan_target.py`'s `ScanTargetNotFoundError`
    rather than duplicating it — a `ScanRun.scan_target_id` with no matching
    (or since-deleted) `ScanTarget` row is a genuine, if unusual, error."""
    from orchestrator.application.use_cases.get_scan_target import ScanTargetNotFoundError
    from orchestrator.workers.tasks import process_scan

    _target, run, task = _make_target_entities()
    task_repo = _FakeTaskRepoForLoad(task)
    run_repo = _FakeRunRepoForLoad(run)
    target_repo = _FakeTargetRepoForLoad(target=None)

    monkeypatch.setattr(process_scan, "SqlAlchemyScanTaskRepository", lambda _s: task_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanRunRepository", lambda _s: run_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanTargetRepository", lambda _s: target_repo)

    settings = _make_target_settings(dast_enabled=True)

    with pytest.raises(ScanTargetNotFoundError):
        asyncio.run(
            process_scan._load_and_start(_FakeSession(), task.id, settings)  # type: ignore[arg-type]
        )


def test_load_and_start_terminal_target_subject_run_never_raises_dast_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-terminal (`completed`/`failed`/`skipped`) target-subject
    task must be a pure idempotent no-op read — never re-fails a settled
    task just because DAST has since been disabled."""
    from orchestrator.domain.value_objects.enums import ScanTaskStatus
    from orchestrator.workers.tasks import process_scan

    target, run, task = _make_target_entities(task_status=ScanTaskStatus.COMPLETED)
    task_repo = _FakeTaskRepoForLoad(task)
    run_repo = _FakeRunRepoForLoad(run)
    target_repo = _FakeTargetRepoForLoad(target)

    monkeypatch.setattr(process_scan, "SqlAlchemyScanTaskRepository", lambda _s: task_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanRunRepository", lambda _s: run_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanTargetRepository", lambda _s: target_repo)

    settings = _make_target_settings(dast_enabled=False)

    result = asyncio.run(
        process_scan._load_and_start(_FakeSession(), task.id, settings)  # type: ignore[arg-type]
    )

    assert result[6] is True  # terminal


def test_run_target_scan_uses_the_target_execution_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 7.1/7.4: sibling of `_checkout_and_scan` for a target-subject
    run — resolves `create_target_scan_execution(...)` and returns its
    `TargetScanExecutionResult.findings` only (no `head_sha` concept)."""
    from orchestrator.domain.ports.target_scan_execution_port import TargetScanExecutionResult
    from orchestrator.workers.tasks import process_scan

    finding = MagicMock()
    execution = MagicMock()
    execution.execute.return_value = TargetScanExecutionResult(findings=[finding])
    monkeypatch.setattr(process_scan, "create_target_scan_execution", lambda *_args: execution)

    findings = process_scan._run_target_scan(
        _TARGET_URL, _TASK_ID, ScannerType.DAST, MagicMock(), MagicMock(), MagicMock()
    )

    assert findings == [finding]
    execution.execute.assert_called_once_with(_TARGET_URL, _TASK_ID, ScannerType.DAST)


def test_complete_target_scan_skips_commit_sha_and_upserts_via_scan_target_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 7.3/7.4: `_complete_target_scan` NEVER calls
    `update_commit_sha` (a `ScanTarget` has no commit concept) and persists
    findings scoped to `ScanSubject(SCAN_TARGET, ...)`, not the repository
    variant."""
    from orchestrator.domain.value_objects.enums import ScanRunStatus, ScanTaskStatus
    from orchestrator.domain.value_objects.scan_subject import ScanSubject, ScanSubjectKind
    from orchestrator.workers.tasks import process_scan

    _target, run, task = _make_target_entities(task_status=ScanTaskStatus.RUNNING)
    task_repo = _FakeTaskRepoForLoad(task)
    run_repo = _FakeRunRepoForLoad(run)

    class _FakeFindingRepo:
        def __init__(self) -> None:
            self.calls: list[tuple[object, uuid.UUID, list[object]]] = []

        async def bulk_upsert_findings(
            self, subject: object, scan_run_id: uuid.UUID, findings: list[object]
        ) -> None:
            self.calls.append((subject, scan_run_id, findings))

    finding_repo = _FakeFindingRepo()

    monkeypatch.setattr(process_scan, "SqlAlchemyScanTaskRepository", lambda _s: task_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyScanRunRepository", lambda _s: run_repo)
    monkeypatch.setattr(process_scan, "SqlAlchemyFindingRepository", lambda _s: finding_repo)

    transitioned, _duration = asyncio.run(
        process_scan._complete_target_scan(
            _FakeSession(),  # type: ignore[arg-type]
            task.id,
            run.id,  # type: ignore[attr-defined]
            _TARGET_ID,
            [],
        )
    )

    assert transitioned is True
    assert finding_repo.calls == [
        (ScanSubject(ScanSubjectKind.SCAN_TARGET, _TARGET_ID), run.id, [])  # type: ignore[attr-defined]
    ]
    assert task_repo.updates == [ScanTaskStatus.COMPLETED]
    assert run_repo.updates == [ScanRunStatus.COMPLETED]


def test_failure_category_classifies_dast_disabled_error() -> None:
    from orchestrator.workers.tasks.process_scan import DastDisabledError, _failure_category

    assert _failure_category(DastDisabledError("dast disabled")) == "dast_disabled"


def test_process_scan_task_dast_disabled_error_is_deterministic_with_no_retry(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Task 7.2: `DastDisabledError` raised by `_load_and_start` is added to
    BOTH the inner reclassification tuple and the outer terminal-classification
    tuple — proven here via the outer one, which is what actually reclassifies
    an exception raised before the `scan.checkout_and_scan` span is even
    entered. Zero container/network calls follow structurally: the exception
    propagates before `_run_target_scan`/`_checkout_and_scan` is ever called."""
    from types import SimpleNamespace

    from orchestrator.workers.tasks import process_scan

    async def _raise_dast_disabled(
        _session: object, _task_id: uuid.UUID, _settings: object
    ) -> None:
        raise process_scan.DastDisabledError("DAST scanning is disabled")

    terminal_calls: list[object] = []

    async def _mark_failed(*_args: object) -> tuple[bool, ScannerType, float]:
        return True, ScannerType.DAST, 12.0

    def _run_async(factory: object) -> object:
        return asyncio.run(factory(None))  # type: ignore[operator]

    monkeypatch.setattr(process_scan, "run_async", _run_async)
    monkeypatch.setattr(process_scan, "_load_and_start", _raise_dast_disabled)
    monkeypatch.setattr(process_scan, "_mark_failed", _mark_failed)
    monkeypatch.setattr(
        process_scan, "record_scan_terminal", lambda *args: terminal_calls.append(args)
    )

    task = SimpleNamespace(request=SimpleNamespace(retries=0), retry=MagicMock())
    process_scan.process_scan_task.run.__func__(task, str(_TASK_ID), docker_client=MagicMock())

    assert task.retry.call_count == 0
    assert terminal_calls == [(ScannerType.DAST, "failed", "dast_disabled", 12.0)]


def test_process_scan_task_target_subject_write_back_span_uses_scan_target_id(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: object
) -> None:
    """Task 7.4: the target-subject dispatch branch's `scan.write_back` span
    carries `scan_target.id`, never `repository.id` (which does not exist
    for this run)."""
    from orchestrator.domain.value_objects.scan_subject import ScanSubject, ScanSubjectKind
    from orchestrator.workers.tasks import process_scan

    loaded = (
        _TARGET_URL,
        None,
        _SCAN_RUN_ID,
        None,
        ScannerType.DAST,
        True,
        False,
        None,
        ScanSubject(ScanSubjectKind.SCAN_TARGET, _TARGET_ID),
    )

    async def _load(*_args: object) -> tuple[object, ...]:
        return loaded

    def _target_scan(*_args: object) -> list[object]:
        return []

    async def _complete(*_args: object) -> tuple[bool, float]:
        return True, 5.0

    monkeypatch.setattr(process_scan, "run_async", lambda factory: asyncio.run(factory(None)))
    monkeypatch.setattr(process_scan, "_load_and_start", _load)
    monkeypatch.setattr(process_scan, "_run_target_scan", _target_scan)
    monkeypatch.setattr(process_scan, "_complete_target_scan", _complete)

    result = process_scan.process_scan_task.apply(
        args=(str(_TASK_ID),), kwargs={"docker_client": MagicMock()}
    )
    result.get()

    spans = {span.name: span for span in span_exporter.get_finished_spans()}  # type: ignore[attr-defined]
    write_back_attrs = spans["scan.write_back"].attributes
    assert write_back_attrs is not None
    assert write_back_attrs["scan_target.id"] == str(_TARGET_ID)
    assert "repository.id" not in write_back_attrs
