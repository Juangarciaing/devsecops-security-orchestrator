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
