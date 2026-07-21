"""`ingest_webhook` use case — single outcome authority for GitHub webhook
intake (design D3). Every branch records exactly one `WebhookDelivery` audit
row EXCEPT the replay/duplicate branch, which explicitly does not re-record
(design data flow: "exists(delivery_id) -> return DUPLICATE (no re-record)").
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.ingest_webhook import ingest_webhook
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.ports.webhook_delivery_port import WebhookDeliveryPort
from orchestrator.domain.value_objects.enums import (
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
    WebhookOutcome,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


class _FakeCodeRepositoryRepository(CodeRepositoryPort):
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, CodeRepository] = {}

    def seed(self, repository: CodeRepository) -> None:
        self._by_id[repository.id] = repository

    async def get_by_id(self, repository_id: uuid.UUID) -> CodeRepository | None:
        return self._by_id.get(repository_id)

    async def get_by_identity(
        self, provider: RepositoryProvider, owner: str, name: str
    ) -> CodeRepository | None:
        for repo in self._by_id.values():
            if repo.identity() == (provider, owner, name):
                return repo
        return None

    async def list_all(self) -> list[CodeRepository]:
        return list(self._by_id.values())

    async def list_active(self) -> list[CodeRepository]:
        return [r for r in self._by_id.values() if r.is_active]

    async def create(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        return repository

    async def update(self, repository: CodeRepository) -> CodeRepository:
        self._by_id[repository.id] = repository
        return repository

    async def soft_delete(self, repository_id: uuid.UUID) -> None:
        repo = self._by_id.get(repository_id)
        if repo is not None:
            repo.is_active = False

    async def delete(self, repository_id: uuid.UUID) -> None:
        self._by_id.pop(repository_id, None)


class _FakeScanRunRepository(ScanRunPort):
    def __init__(self) -> None:
        self.created: list[ScanRun] = []
        self._by_id: dict[uuid.UUID, ScanRun] = {}

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        return self._by_id.get(scan_run_id)

    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        return [r for r in self._by_id.values() if r.repository_id == repository_id]

    async def create(self, scan_run: ScanRun) -> ScanRun:
        self._by_id[scan_run.id] = scan_run
        self.created.append(scan_run)
        return scan_run

    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        run = self._by_id[scan_run_id]
        run.status = status
        return run

    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        ordered = sorted(self._by_id.values(), key=lambda r: r.created_at, reverse=True)
        return ordered[offset : offset + limit]

    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        return []  # pragma: no cover — unused in these tests


class _FakeScanTaskRepository(ScanTaskPort):
    def __init__(self) -> None:
        self.created: list[ScanTask] = []
        self._by_id: dict[uuid.UUID, ScanTask] = {}

    async def get_by_id(self, scan_task_id: uuid.UUID) -> ScanTask | None:
        return self._by_id.get(scan_task_id)

    async def list_by_scan_run(self, scan_run_id: uuid.UUID) -> list[ScanTask]:
        return [t for t in self._by_id.values() if t.scan_run_id == scan_run_id]

    async def create(self, scan_task: ScanTask) -> ScanTask:
        self._by_id[scan_task.id] = scan_task
        self.created.append(scan_task)
        return scan_task

    async def update_status(self, scan_task_id: uuid.UUID, status: ScanTaskStatus) -> ScanTask:
        task = self._by_id[scan_task_id]
        task.status = status
        return task

    async def find_active_task(
        self, repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        return None


class _FakeWebhookDeliveryRepository(WebhookDeliveryPort):
    def __init__(self) -> None:
        self.recorded: list[WebhookDelivery] = []
        self._delivery_ids: set[str] = set()

    def seed_existing(self, delivery_id: str) -> None:
        self._delivery_ids.add(delivery_id)

    async def exists(self, delivery_id: str) -> bool:
        return delivery_id in self._delivery_ids

    async def record(self, delivery: WebhookDelivery) -> None:
        self.recorded.append(delivery)
        if delivery.delivery_id is not None:
            self._delivery_ids.add(delivery.delivery_id)


def _make_repository(**overrides: object) -> CodeRepository:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "provider": RepositoryProvider.GITHUB,
        "owner": "acme",
        "name": "widgets",
        "clone_url": "https://github.com/acme/widgets.git",
        "default_branch": "main",
        "credential_ref": None,
        "is_active": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CodeRepository(**defaults)  # type: ignore[arg-type]


def _push_body(**overrides: object) -> bytes:
    defaults: dict[object, object] = {
        "ref": "refs/heads/main",
        "after": "deadbeef1234",
        "repository": {"full_name": "acme/widgets"},
        "head_commit": {"id": "headcommitsha"},
    }
    defaults.update(overrides)
    return json.dumps(defaults).encode()


def _ports() -> tuple[
    _FakeWebhookDeliveryRepository,
    _FakeCodeRepositoryRepository,
    _FakeScanRunRepository,
    _FakeScanTaskRepository,
]:
    return (
        _FakeWebhookDeliveryRepository(),
        _FakeCodeRepositoryRepository(),
        _FakeScanRunRepository(),
        _FakeScanTaskRepository(),
    )


def test_valid_push_default_branch_triggers_scan_and_records_accepted() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository()
    repository_port.seed(repository)

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-1",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.ACCEPTED
    assert task_id is not None
    assert len(scan_run_port.created) == 1
    assert scan_run_port.created[0].trigger == "webhook"
    assert len(scan_task_port.created) == 1
    assert scan_task_port.created[0].id == task_id
    assert len(webhook_port.recorded) == 1
    record = webhook_port.recorded[0]
    assert record.outcome == WebhookOutcome.ACCEPTED
    assert record.signature_valid is True
    assert record.delivery_id == "delivery-1"
    assert record.repository_full_name == "acme/widgets"
    assert record.ref == "refs/heads/main"
    assert record.commit_sha == "deadbeef1234"


def test_non_push_event_is_ignored_and_records_ignored_event() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=b"{}",
            event_type="ping",
            delivery_id="delivery-ping",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.IGNORED_EVENT
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.IGNORED_EVENT
    assert webhook_port.recorded[0].signature_valid is True


def test_replayed_delivery_id_is_a_no_op_and_does_not_re_record() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository()
    repository_port.seed(repository)
    webhook_port.seed_existing("delivery-replay")

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-replay",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.DUPLICATE
    assert task_id is None
    assert scan_run_port.created == []
    assert webhook_port.recorded == []  # no re-record — design: "no re-record"


def test_malformed_payload_records_invalid_payload_and_never_raises() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=b"not-json-at-all",
            event_type="push",
            delivery_id="delivery-malformed",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.INVALID_PAYLOAD
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.INVALID_PAYLOAD


def test_unknown_repository_records_ignored_unknown_repo() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-unknown",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.IGNORED_UNKNOWN_REPO
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.IGNORED_UNKNOWN_REPO
    assert webhook_port.recorded[0].repository_full_name == "acme/widgets"


def test_inactive_repository_records_ignored_inactive_repo() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository(is_active=False)
    repository_port.seed(repository)

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-inactive",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.IGNORED_INACTIVE_REPO
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.IGNORED_INACTIVE_REPO


def test_non_default_branch_records_ignored_non_default_branch() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository(default_branch="main")
    repository_port.seed(repository)

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(ref="refs/heads/feature-branch"),
            event_type="push",
            delivery_id="delivery-branch",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.IGNORED_NON_DEFAULT_BRANCH
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.IGNORED_NON_DEFAULT_BRANCH
    assert webhook_port.recorded[0].ref == "refs/heads/feature-branch"


def test_invalid_signature_records_rejected_signature_with_signature_valid_false() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=False,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-rejected",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.REJECTED_SIGNATURE
    assert task_id is None
    assert scan_run_port.created == []
    assert len(webhook_port.recorded) == 1
    record = webhook_port.recorded[0]
    assert record.outcome == WebhookOutcome.REJECTED_SIGNATURE
    assert record.signature_valid is False
    # Deliberately NOT the real header value: a rejected-signature delivery
    # precedes the exists()-idempotency checkpoint, so recording the real
    # delivery_id here could collide with a later legitimate push carrying
    # the same id, or with a retried rejected request (design: "NULL when
    # absent/rejected").
    assert record.delivery_id is None


def test_active_task_dedup_inside_trigger_scan_yields_accepted_with_no_task_id() -> None:
    """`trigger_scan`'s own idempotency (D3 defense-in-depth) can report
    `created=False` for a push that otherwise passes every ingest check —
    outcome stays ACCEPTED (the delivery itself was valid and processed),
    but no new task_id is returned, so the router does not re-enqueue."""
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository()
    repository_port.seed(repository)

    existing_run = ScanRun(
        id=uuid.uuid4(),
        repository_id=repository.id,
        status=ScanRunStatus.PENDING,
        trigger="webhook",
        commit_sha="deadbeef1234",
        ref="deadbeef1234",
        created_at=_NOW,
    )
    scan_run_port._by_id[existing_run.id] = existing_run
    existing_task = ScanTask(
        id=uuid.uuid4(),
        scan_run_id=existing_run.id,
        scanner_type=ScannerType.SECRETS,
        status=ScanTaskStatus.PENDING,
    )
    scan_task_port._by_id[existing_task.id] = existing_task

    async def _find_active_task(
        repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        if repository_id == repository.id and commit_sha == "deadbeef1234":
            return existing_task
        return None

    scan_task_port.find_active_task = _find_active_task  # type: ignore[method-assign]

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id="delivery-dedup",
            source_ip="203.0.113.1",
        )
    )

    assert outcome == WebhookOutcome.ACCEPTED
    assert task_id is None
    assert scan_run_port.created == []
    assert scan_task_port.created == []
    assert len(webhook_port.recorded) == 1
    assert webhook_port.recorded[0].outcome == WebhookOutcome.ACCEPTED


def test_every_recorded_delivery_gets_a_fresh_uuid_and_received_at() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()

    asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=b"{}",
            event_type="ping",
            delivery_id=None,
            source_ip=None,
        )
    )

    assert len(webhook_port.recorded) == 1
    record = webhook_port.recorded[0]
    assert isinstance(record.id, uuid.UUID)
    assert isinstance(record.received_at, datetime)


def test_missing_delivery_id_on_push_skips_idempotency_check() -> None:
    webhook_port, repository_port, scan_run_port, scan_task_port = _ports()
    repository = _make_repository()
    repository_port.seed(repository)

    outcome, task_id = asyncio.run(
        ingest_webhook(
            webhook_port,
            repository_port,
            scan_run_port,
            scan_task_port,
            signature_valid=True,
            raw_body=_push_body(),
            event_type="push",
            delivery_id=None,
            source_ip=None,
        )
    )

    assert outcome == WebhookOutcome.ACCEPTED
    assert task_id is not None
