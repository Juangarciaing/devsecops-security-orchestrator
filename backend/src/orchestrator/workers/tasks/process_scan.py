"""`process_scan_task` — the real Module 6/7 scan flow (D1-D6).

## Flow
    run_async: load task -> run -> repository; pending -> running    [DB]
    sync:      create_scan_execution(scanner_type, ...)              [factory, Module 13c PR5b]
               execution.execute(clone_url, ref, scan_task_id, ...)  [checkout + scan containers]
               # descriptor executor's GitCheckout(...).checkout(...) yields
               # a Workspace whose __exit__ force-removes the volume
               # (finally); it invokes the scanner's fixed descriptor, then
               # adapter.parse(RunResult, scan_task_id) -> list[Finding]
    run_async: persist resolved commit_sha + bulk_upsert_findings(...)     [DB, dedup on
               (repository_id, fingerprint); task + run -> completed        Module 7 D4/D6]

Container work (checkout + scan) is sync/blocking (the `docker` SDK itself
is sync, Module 6 D3) and runs OUTSIDE any async DB session/event loop —
`run_async` is called twice, before and after, never around it.

## Failure classification (D5)
- `CheckoutFailedError` / `GitleaksFailedError` / `PipAuditFailedError` /
  `SastFailedError` / `SemgrepFailedError` (bad ref, private repo, a genuine
  non-{0,2} Gitleaks exit code, a malformed/empty/timed-out pip-audit report,
  a missing-JSON/malformed/timed-out sast-scanner or semgrep report, or a
  wall-clock timeout) are DETERMINISTIC — a retry cannot fix them. These go
  straight to `failed`, bypassing Module 5's retry/backoff machinery entirely
  (one attempt only). (Module 11 D7: `PipAuditFailedError` added alongside
  the two pre-existing Gitleaks/Checkout classifications; Module 11 D5
  (AST-SAST, PR2): `SastFailedError` added the same way; Module 11 D8
  (Semgrep, PR3): `SemgrepFailedError` added the same way — additive,
  backward-compatible.)
- Any OTHER exception raised while checking out/scanning (Docker-daemon
  blips, network errors, ...) is wrapped as `TransientScanError` and handed
  to the EXACT SAME retry/backoff loop Module 5 already built — this module
  only changes WHAT the task body does when it runs, never the surrounding
  state-machine/retry plumbing.
- `CredentialUnavailableError` (secrets-manager PR6, design D9): a stored
  credential could not be unsealed for this attempt (wrong/rotated key,
  corrupted ciphertext, or an unset `credential_encryption_key`) — also
  DETERMINISTIC, straight to `failed`, no retry, and the repository is NEVER
  automatically deactivated (spec: "Decrypt Failure Is Credential-Free and
  Non-Deactivating").

## Credential resolution (secrets-manager PR6, design D9)

`_load_and_start` unseals a repository's stored credential (if any) INSIDE
the same transaction as the `pending -> running` transition and appends
exactly one `CredentialAccessLog` row per attempt (`USED` /
`DECRYPT_FAILED` / `KEY_UNAVAILABLE`, via `_resolve_credential`) — a public
repository (`credential_ciphertext is None`) never touches this path at all
(spec: "Public Repository Checkout Unaffected"). The resulting `Secret` (or
`None`) is threaded through `_checkout_and_scan` into
`ScanExecutionPort.execute(..., credential=...)` (PR5).

`container_runner`/`docker_client` are test-only injection kwargs (mirrors
Module 5's `simulate_failure`/`fail_attempts` precedent): production callers
never pass them (defaults construct a real `DockerContainerRunner`/
`docker.from_env()`); tests inject a `FakeContainerRunner` + a `MagicMock`
docker client instead (see `tests/integration/test_process_scan_task.py`,
which mirrors the `FakeContainerRunner`/`MagicMock` double already
established by `tests/unit/infrastructure/test_git_checkout.py`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

import docker
from celery import Task
from celery.exceptions import MaxRetriesExceededError
from celery.utils.log import get_task_logger
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.credential_access_log import CredentialAccessLog
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.ports.credential_store_port import (
    CredentialUnsealError,
    SealedCredential,
)
from orchestrator.domain.value_objects.enums import (
    CredentialAccessOutcome,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
)
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.container.scan_execution_factory import create_scan_execution
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    CodeRepositoryNotFoundError,
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.credential_access_log_repository import (
    SqlAlchemyCredentialAccessLogRepository,
)
from orchestrator.infrastructure.db.repositories.finding_repository import (
    SqlAlchemyFindingRepository,
)
from orchestrator.infrastructure.db.repositories.scan_run_repository import (
    ScanRunNotFoundError,
    SqlAlchemyScanRunRepository,
)
from orchestrator.infrastructure.db.repositories.scan_task_repository import (
    ScanTaskNotFoundError,
    SqlAlchemyScanTaskRepository,
)
from orchestrator.infrastructure.observability.metrics import (
    record_scan_findings,
    record_scan_retried,
    record_scan_started,
    record_scan_terminal,
    record_scanner_duration,
)
from orchestrator.infrastructure.scanners.ast_sast_adapter import SastFailedError
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksFailedError
from orchestrator.infrastructure.scanners.pip_audit_adapter import PipAuditFailedError
from orchestrator.infrastructure.scanners.semgrep_adapter import SemgrepFailedError
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError
from orchestrator.workers.backoff import backoff_jitter
from orchestrator.workers.celery_app import celery_app
from orchestrator.workers.db import run_async

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.entities.code_repository import CodeRepository
    from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort
    from orchestrator.domain.ports.credential_access_log_port import CredentialAccessLogPort
    from orchestrator.domain.ports.credential_store_port import CredentialStorePort
    from orchestrator.domain.value_objects.secret import Secret
    from orchestrator.infrastructure.config.settings import Settings

logger = get_task_logger(__name__)

MAX_RETRIES = 5


class TransientScanError(RuntimeError):
    """A retryable, non-deterministic failure (Docker-daemon/network blip, D5).

    NEVER raised for a deterministic outcome (`CheckoutFailedError`,
    `GitleaksFailedError`) — those bypass retry entirely and go straight to
    `failed` (D5).
    """


class CredentialUnavailableError(RuntimeError):
    """A repository's stored credential could not be unsealed for this scan
    attempt (secrets-manager PR6, design D9): wrong/rotated encryption key,
    corrupted ciphertext, or an unset `credential_encryption_key`.

    DETERMINISTIC (D5) — a retry cannot fix a decrypt failure, so this goes
    straight to `failed` like `CheckoutFailedError`. The message is
    credential-free by construction: it never carries the ciphertext, the
    decrypted plaintext, or key material. The repository is NEVER
    automatically deactivated (spec: "Decrypt Failure Is Credential-Free and
    Non-Deactivating").
    """


async def _resolve_credential(
    credential_access_log_port: CredentialAccessLogPort,
    credential_store: CredentialStorePort,
    settings: Settings,
    repository: CodeRepository,
    scan_task_id: uuid.UUID,
    *,
    actor: str,
    actor_user_id: uuid.UUID | None,
) -> Secret | None:
    """Resolve `repository`'s stored credential for one scan attempt (D9).

    Returns `None` unchanged when the repository has no stored credential —
    a public repository never appends an audit row or calls `unseal()`
    (spec: "Public Repository Checkout Unaffected").

    When a credential IS stored, appends exactly ONE `CredentialAccessLog`
    row for this attempt:
    - `KEY_UNAVAILABLE` when `Settings.credential_encryption_key` is unset.
      Checked explicitly BEFORE calling `unseal()` — `FernetCredentialStore`
      raises the SAME `CredentialUnsealError` for a missing key as for a
      wrong/corrupted one (there is only one unseal-failure exception type,
      design D2), so this case is distinguished here, not by inspecting the
      exception.
    - `DECRYPT_FAILED` for any other `CredentialUnsealError` (wrong/rotated
      key, corrupted ciphertext).
    - `USED` on success.

    Raises `CredentialUnavailableError` (credential-free) for the first two
    outcomes — callers must fail the scan deterministically without ever
    touching `repository.is_active`.
    """
    if repository.credential_ciphertext is None:
        return None

    kind = repository.credential_kind
    assert kind is not None  # invariant: ciphertext implies a credential_kind

    async def _append(outcome: CredentialAccessOutcome) -> None:
        await credential_access_log_port.append(
            CredentialAccessLog(
                id=uuid.uuid4(),
                repository_id=repository.id,
                scan_task_id=scan_task_id,
                credential_kind=kind,
                actor=actor,
                actor_user_id=actor_user_id,
                outcome=outcome,
                accessed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    if settings.credential_encryption_key is None:
        await _append(CredentialAccessOutcome.KEY_UNAVAILABLE)
        raise CredentialUnavailableError(
            "credential storage is not configured on this deployment; the scan cannot proceed"
        )

    sealed = SealedCredential(kind=kind, ciphertext=repository.credential_ciphertext)
    try:
        secret = credential_store.unseal(sealed)
    except CredentialUnsealError:
        await _append(CredentialAccessOutcome.DECRYPT_FAILED)
        raise CredentialUnavailableError(
            "stored credential could not be decrypted; re-enter the credential for this repository"
        ) from None

    await _append(CredentialAccessOutcome.USED)
    return secret


async def _load_and_start(
    session: AsyncSession, scan_task_id: uuid.UUID, settings: Settings
) -> tuple[str, str, uuid.UUID, uuid.UUID, ScannerType, bool, bool, Secret | None]:
    """Load the repo's `clone_url` + the run's `ref`; transition `pending -> running`.

    Returns `(clone_url, ref, scan_run_id, repository_id, scanner_type,
    transitioned, terminal, credential)`. Idempotent on the `pending ->
    running` transition, matching Module 5's original convention.

    `repository_id`/`scanner_type` are returned so `_checkout_and_scan`
    (factory-routed, Module 13c PR5b) and `_complete_scan`
    (`bulk_upsert_findings`, Module 7 D4/D6) don't need to re-load `task`/
    `repository` themselves.

    `credential` (secrets-manager PR6, design D9): `None` for a public
    repository, byte-for-byte unchanged from before this PR. For a
    credentialed repository, `_resolve_credential` unseals it and appends
    ONE `CredentialAccessLog` row INSIDE the same transaction/commit as the
    `pending -> running` update (or, on a retry with no fresh transition,
    committed on its own) — every non-terminal attempt is audited, not just
    the first. A decrypt/key failure raises `CredentialUnavailableError`
    AFTER that commit still lands (the audit row and any `running`
    transition are never rolled back by a later failure).
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    code_repository_repo = SqlAlchemyCodeRepositoryRepository(session)
    credential_access_log_repo = SqlAlchemyCredentialAccessLogRepository(session)

    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)
    run = await scan_run_repo.get_by_id(task.scan_run_id)
    if run is None:
        raise ScanRunNotFoundError(task.scan_run_id)
    repository = await code_repository_repo.get_by_id(run.repository_id)
    if repository is None:
        raise CodeRepositoryNotFoundError(run.repository_id)

    now = datetime.now(UTC).replace(tzinfo=None)
    transitioned = task.status == ScanTaskStatus.PENDING
    terminal = task.status in (
        ScanTaskStatus.COMPLETED,
        ScanTaskStatus.FAILED,
        ScanTaskStatus.SKIPPED,
    )

    credential: Secret | None = None
    has_credential = repository.credential_ciphertext is not None

    if not terminal and has_credential:
        credential_store = FernetCredentialStore(encryption_key=settings.credential_encryption_key)
        try:
            credential = await _resolve_credential(
                credential_access_log_repo,
                credential_store,
                settings,
                repository,
                scan_task_id,
                actor=run.trigger,
                actor_user_id=run.triggered_by_user_id,
            )
        finally:
            if transitioned:
                await scan_task_repo.update_status(
                    scan_task_id, ScanTaskStatus.RUNNING, started_at=now
                )
                await scan_run_repo.update_status(
                    task.scan_run_id, ScanRunStatus.RUNNING, started_at=now
                )
            await session.commit()
    elif not terminal and transitioned:
        await scan_task_repo.update_status(scan_task_id, ScanTaskStatus.RUNNING, started_at=now)
        await scan_run_repo.update_status(task.scan_run_id, ScanRunStatus.RUNNING, started_at=now)
        await session.commit()

    return (
        repository.clone_url,
        run.ref,
        task.scan_run_id,
        repository.id,
        task.scanner_type,
        transitioned,
        terminal,
        credential,
    )


def _checkout_and_scan(
    clone_url: str,
    ref: str,
    scan_task_id: uuid.UUID,
    scanner_type: ScannerType,
    runner: ContainerRunnerPort,
    docker_client: DockerClient,
    settings: Settings,
    credential: Secret | None = None,
) -> tuple[str, list[Finding]]:
    """Sync/blocking: resolve the descriptor executor, checkout, scan, parse.
    Runs OUTSIDE any async DB session/event loop (Module 6 D3).

    The executor is resolved via `create_scan_execution(scanner_type, ...)`
    (Module 13c PR5b factory) instead of a hardcoded adapter — this is what
    actually makes `ScanTask.scanner_type` meaningful. Raises
    `UnsupportedScannerTypeError` (via `create_scan_execution`) for any
    `scanner_type` with no descriptor; `CheckoutFailedError` (deterministic,
    from `GitCheckout`), `GitleaksFailedError` (deterministic, from
    `GitleaksAdapter.parse()`), `PipAuditFailedError` (deterministic,
    from `PipAuditAdapter.parse()`, Module 11 D7),
    `SastFailedError` (deterministic, from `AstSastAdapter.parse()`,
    Module 11 D5, PR2), or `SemgrepFailedError` (deterministic, from
    `SemgrepAdapter.parse()`, Module 11 D8, PR3) unchanged — callers
    classify those as non-retryable (D5). Any OTHER exception (including
    `UnsupportedScannerTypeError`) is left to propagate to the caller, which
    wraps it as `TransientScanError`.

    `credential` (secrets-manager PR6, additive, defaulted): the `Secret`
    resolved by `_load_and_start`/`_resolve_credential`, threaded straight
    through to `ScanExecutionPort.execute(..., credential=...)` (PR5). `None`
    (the default) reproduces today's public-repo behavior byte-for-byte.
    """
    execution = create_scan_execution(runner, docker_client, settings, scanner_type)
    result = execution.execute(clone_url, ref, scan_task_id, scanner_type, credential=credential)
    return result.head_sha, result.findings


async def _complete_scan(
    session: AsyncSession,
    scan_task_id: uuid.UUID,
    scan_run_id: uuid.UUID,
    repository_id: uuid.UUID,
    head_sha: str,
    findings: list[Finding],
) -> tuple[bool, float]:
    """Persist the resolved HEAD SHA + `Finding`s; `task`/`run` -> `completed`.

    Zero `findings` (a clean repo) is a valid, successful outcome (D4/spec) —
    NOT treated as failure (`bulk_upsert_findings` no-ops on an empty list).

    Persistence is ONE `bulk_upsert_findings(repository_id, scan_run_id,
    findings)` call (Module 7 D4/D6) — REPLACES the former per-finding
    `create()` loop. This is what actually gives cross-run dedup on re-scans:
    a `Finding` whose `(repository_id, fingerprint)` was already seen has its
    `last_seen_scan_run_id` advanced (and `status` left untouched — suppressed
    stays suppressed) instead of inserting a duplicate row; a brand-new
    fingerprint inserts with `first_seen_scan_run_id == last_seen_scan_run_id
    == scan_run_id`.
    """
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)
    finding_repo = SqlAlchemyFindingRepository(session)
    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)
    if task.status != ScanTaskStatus.RUNNING:
        return False, 0.0

    await scan_run_repo.update_commit_sha(scan_run_id, head_sha)
    await finding_repo.bulk_upsert_findings(repository_id, scan_run_id, findings)

    completed_at = datetime.now(UTC).replace(tzinfo=None)
    await scan_task_repo.update_status(
        scan_task_id, ScanTaskStatus.COMPLETED, completed_at=completed_at
    )
    await scan_run_repo.update_status(
        scan_run_id, ScanRunStatus.COMPLETED, completed_at=completed_at
    )
    await session.commit()
    return True, logical_scan_duration_seconds(task.started_at, completed_at)


async def _mark_failed(
    session: AsyncSession, scan_task_id: uuid.UUID, error_message: str
) -> tuple[bool, ScannerType, float]:
    """Terminal `failed` transition for both `ScanTask` and its `ScanRun` (D5)."""
    scan_task_repo = SqlAlchemyScanTaskRepository(session)
    scan_run_repo = SqlAlchemyScanRunRepository(session)

    task = await scan_task_repo.get_by_id(scan_task_id)
    if task is None:
        raise ScanTaskNotFoundError(scan_task_id)
    if task.status not in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
        return False, task.scanner_type, 0.0

    now = datetime.now(UTC).replace(tzinfo=None)
    await scan_task_repo.update_status(
        scan_task_id, ScanTaskStatus.FAILED, completed_at=now, error_message=error_message
    )
    await scan_run_repo.update_status(task.scan_run_id, ScanRunStatus.FAILED, completed_at=now)
    await session.commit()
    return True, task.scanner_type, logical_scan_duration_seconds(task.started_at, now)


def logical_scan_duration_seconds(started_at: datetime | None, completed_at: datetime) -> float:
    return max(0.0, (completed_at - (started_at or completed_at)).total_seconds())


def _failure_category(error: Exception) -> str:
    if isinstance(error, CheckoutFailedError):
        return "checkout"
    if isinstance(error, CredentialUnavailableError):
        return "credential"
    if "timeout" in str(error).lower() or "timed out" in str(error).lower():
        return "timeout"
    if isinstance(error, TransientScanError):
        return "container_runtime"
    return "scanner"


@celery_app.task(bind=True, max_retries=MAX_RETRIES)  # type: ignore[untyped-decorator]
def process_scan_task(
    self: Task,
    scan_task_id: str,
    container_runner: ContainerRunnerPort | None = None,
    docker_client: DockerClient | None = None,
) -> None:
    """Run the real scan for `scan_task_id` (a stringified UUID).

    `container_runner`/`docker_client` are test-only injection hooks (see
    module docstring) — production callers never pass them.
    """
    task_id = uuid.UUID(scan_task_id)
    settings = get_settings()
    client = docker_client if docker_client is not None else docker.from_env()
    runner = container_runner if container_runner is not None else DockerContainerRunner(client)
    tracer = trace.get_tracer(__name__)

    try:
        try:
            with tracer.start_as_current_span("scan.load_and_start"):
                loaded = run_async(lambda session: _load_and_start(session, task_id, settings))
                clone_url, ref, scan_run_id, repository_id, scanner_type = loaded[:5]
                started, terminal = loaded[5:7] if len(loaded) >= 7 else (False, False)
                credential = loaded[7] if len(loaded) >= 8 else None
            if terminal:
                return
            if started:
                record_scan_started(scanner_type)

            with tracer.start_as_current_span("scan.checkout_and_scan") as checkout_span:
                # Module 13a threat matrix: `scanner_type` only — NEVER
                # `clone_url`/`ref` (may embed credentials/branch secrets).
                checkout_span.set_attribute("scanner_type", scanner_type.value)
                scanner_started = monotonic()
                try:
                    head_sha, findings = _checkout_and_scan(
                        clone_url, ref, task_id, scanner_type, runner, client, settings, credential
                    )
                except (
                    CheckoutFailedError,
                    GitleaksFailedError,
                    PipAuditFailedError,
                    SastFailedError,
                    SemgrepFailedError,
                ):
                    raise
                except Exception as exc:
                    # Docker-daemon/network blip, not a deterministic checkout/scan
                    # failure (D5) — hand off to Module 5's existing retry/backoff.
                    raise TransientScanError(str(exc)) from exc
                scanner_duration = monotonic() - scanner_started

            with tracer.start_as_current_span("scan.write_back") as write_back_span:
                write_back_span.set_attribute("db.system", "postgresql")
                write_back_span.set_attribute("findings.count", len(findings))
                write_back_span.set_attribute("repository.id", str(repository_id))
                write_back_span.set_attribute("scan_run.id", str(scan_run_id))
                transitioned, scan_duration = run_async(
                    lambda session: _complete_scan(
                        session, task_id, scan_run_id, repository_id, head_sha, findings
                    )
                ) or (False, 0.0)
                if transitioned:
                    record_scan_terminal(scanner_type, "completed", "none", scan_duration)
                    record_scanner_duration(scanner_type, "success", scanner_duration)
                    record_scan_findings(scanner_type, len(findings))
        finally:
            if docker_client is None:
                client.close()
    except (
        CheckoutFailedError,
        GitleaksFailedError,
        PipAuditFailedError,
        SastFailedError,
        SemgrepFailedError,
        CredentialUnavailableError,
    ) as exc:
        error_message = str(exc)
        logger.warning("scan_task %s failed deterministically: %s", task_id, error_message)
        transitioned, scanner_type, scan_duration = run_async(
            lambda session: _mark_failed(session, task_id, error_message)
        )
        if transitioned:
            record_scan_terminal(scanner_type, "failed", _failure_category(exc), scan_duration)
    except TransientScanError as exc:
        error_message = str(exc)
        try:
            # The counter is deliberately adjacent to the retry call: a terminal
            # exhausted branch below emits only terminal failure telemetry.
            if self.request.retries < MAX_RETRIES:
                record_scan_retried(scanner_type, _failure_category(exc))
            self.retry(exc=exc, countdown=backoff_jitter(self.request.retries))
        except (MaxRetriesExceededError, TransientScanError):
            # `self.retry(exc=exc, ...)`, once `max_retries` is exhausted,
            # re-raises the ORIGINAL `exc` (here, `TransientScanError`)
            # rather than `MaxRetriesExceededError` when `exc` was given —
            # catch both to make the terminal `failed` transition explicit
            # and guaranteed either way (D5, Module 5 precedent).
            logger.warning("scan_task %s exhausted retries: %s", task_id, error_message)
            transitioned, scanner_type, scan_duration = run_async(
                lambda session: _mark_failed(session, task_id, error_message)
            )
            if transitioned:
                record_scan_terminal(scanner_type, "failed", _failure_category(exc), scan_duration)
