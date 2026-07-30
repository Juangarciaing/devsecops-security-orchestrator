"""Entity <-> ORM model round-trip tests for all 4 aggregates.

Uses in-memory objects only (plain instantiation, no DB session/connection) —
verifies `to_model`/`to_entity` preserve every field.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.credential_access_log import CredentialAccessLog
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.entities.user import User
from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.value_objects.enums import (
    CredentialAccessOutcome,
    CredentialKind,
    FindingSeverity,
    FindingStatus,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
    UserRole,
    WebhookOutcome,
)
from orchestrator.infrastructure.db.mappers import (
    api_key_to_entity,
    api_key_to_model,
    code_repository_to_entity,
    code_repository_to_model,
    credential_access_log_to_entity,
    credential_access_log_to_model,
    finding_to_entity,
    finding_to_model,
    scan_run_to_entity,
    scan_run_to_model,
    scan_target_to_entity,
    scan_target_to_model,
    scan_task_to_entity,
    scan_task_to_model,
    user_to_entity,
    user_to_model,
    webhook_delivery_to_entity,
    webhook_delivery_to_model,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_code_repository_round_trip() -> None:
    entity = CodeRepository(
        id=uuid.uuid4(),
        provider=RepositoryProvider.GITHUB,
        owner="acme",
        name="widgets",
        clone_url="https://github.com/acme/widgets.git",
        default_branch="main",
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        credential_ciphertext="gAAAAA...opaque",
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = code_repository_to_model(entity)
    round_tripped = code_repository_to_entity(model)

    assert round_tripped == entity


def test_code_repository_round_trip_with_no_credential_and_inactive() -> None:
    entity = CodeRepository(
        id=uuid.uuid4(),
        provider=RepositoryProvider.GITLAB,
        owner="acme",
        name="gadgets",
        clone_url="https://gitlab.com/acme/gadgets.git",
        default_branch="develop",
        credential_kind=None,
        credential_ciphertext=None,
        is_active=False,
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = code_repository_to_model(entity)
    round_tripped = code_repository_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.credential_kind is None
    assert round_tripped.credential_ciphertext is None


def test_scan_target_round_trip() -> None:
    entity = ScanTarget(
        id=uuid.uuid4(),
        name="acme-public-site",
        target_url="https://example.com",
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = scan_target_to_model(entity)
    round_tripped = scan_target_to_entity(model)

    assert round_tripped == entity


def test_scan_target_round_trip_when_inactive() -> None:
    entity = ScanTarget(
        id=uuid.uuid4(),
        name="acme-decommissioned-site",
        target_url="https://old.example.com",
        is_active=False,
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = scan_target_to_model(entity)
    round_tripped = scan_target_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.is_active is False
    assert round_tripped.is_active is False


def test_scan_run_round_trip() -> None:
    entity = ScanRun(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        status=ScanRunStatus.RUNNING,
        trigger="push",
        commit_sha="abc123",
        ref="refs/heads/main",
        created_at=_NOW,
        started_at=_NOW,
        completed_at=None,
        triggered_by_user_id=uuid.uuid4(),
    )

    model = scan_run_to_model(entity)
    round_tripped = scan_run_to_entity(model)

    assert round_tripped == entity


def test_scan_run_round_trip_with_no_triggered_by_user_id() -> None:
    """A webhook-triggered scan never has an authenticated actor (design D8)."""
    entity = ScanRun(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        status=ScanRunStatus.PENDING,
        trigger="webhook",
        commit_sha="abc123",
        ref="refs/heads/main",
        created_at=_NOW,
    )

    model = scan_run_to_model(entity)
    round_tripped = scan_run_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.triggered_by_user_id is None


def test_scan_task_round_trip() -> None:
    entity = ScanTask(
        id=uuid.uuid4(),
        scan_run_id=uuid.uuid4(),
        scanner_type=ScannerType.SAST,
        status=ScanTaskStatus.FAILED,
        started_at=_NOW,
        completed_at=_NOW,
        error_message="boom",
    )

    model = scan_task_to_model(entity)
    round_tripped = scan_task_to_entity(model)

    assert round_tripped == entity


def test_finding_round_trip() -> None:
    entity = Finding(
        id=uuid.uuid4(),
        scan_task_id=uuid.uuid4(),
        severity=FindingSeverity.CRITICAL,
        rule_id="rule-1",
        title="Hardcoded secret",
        fingerprint="fp-1",
        created_at=_NOW,
        updated_at=_NOW,
        status=FindingStatus.SUPPRESSED,
        description="A secret was hardcoded",
        file_path="src/app.py",
        line_number=42,
        raw_evidence={"match": "AKIA..."},
        snippet="API_KEY = 'AKIA...'",
        repository_id=uuid.uuid4(),
        first_seen_scan_run_id=uuid.uuid4(),
        last_seen_scan_run_id=uuid.uuid4(),
    )

    model = finding_to_model(entity)
    round_tripped = finding_to_entity(model)

    assert round_tripped == entity


def test_finding_round_trip_with_null_repository_and_scan_run_tracking() -> None:
    """`repository_id`/`first_seen_scan_run_id`/`last_seen_scan_run_id` default
    to `None` on the entity (Module 7 PR2: additive, non-breaking for callers —
    e.g. `GitleaksAdapter.parse()` — that don't populate them yet)."""
    entity = Finding(
        id=uuid.uuid4(),
        scan_task_id=uuid.uuid4(),
        severity=FindingSeverity.HIGH,
        rule_id="rule-2",
        title="Hardcoded secret",
        fingerprint="fp-2",
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = finding_to_model(entity)
    round_tripped = finding_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.repository_id is None
    assert round_tripped.first_seen_scan_run_id is None
    assert round_tripped.last_seen_scan_run_id is None


def test_user_round_trip() -> None:
    entity = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        role=UserRole.ADMIN,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )

    model = user_to_model(entity)
    round_tripped = user_to_entity(model)

    assert round_tripped == entity


def test_api_key_round_trip() -> None:
    entity = ApiKey(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        key_prefix="dso_abc12345",
        hashed_key="hashed-secret",
        created_at=_NOW,
        last_used_at=_NOW,
        revoked_at=None,
    )

    model = api_key_to_model(entity)
    round_tripped = api_key_to_entity(model)

    assert round_tripped == entity


def test_webhook_delivery_round_trip() -> None:
    entity = WebhookDelivery(
        id=uuid.uuid4(),
        signature_valid=True,
        outcome=WebhookOutcome.ACCEPTED,
        received_at=_NOW,
        delivery_id="delivery-1",
        event_type="push",
        source_ip="203.0.113.5",
        repository_full_name="acme/widgets",
        ref="refs/heads/main",
        commit_sha="c" * 40,
    )

    model = webhook_delivery_to_model(entity)
    round_tripped = webhook_delivery_to_entity(model)

    assert round_tripped == entity


def test_webhook_delivery_round_trip_with_null_delivery_id_on_rejected_signature() -> None:
    """Rejected/header-less deliveries never populate `delivery_id` — the
    mapper must preserve `None` rather than coercing it."""
    entity = WebhookDelivery(
        id=uuid.uuid4(),
        signature_valid=False,
        outcome=WebhookOutcome.REJECTED_SIGNATURE,
        received_at=_NOW,
        delivery_id=None,
        event_type=None,
        source_ip="203.0.113.5",
        repository_full_name=None,
        ref=None,
        commit_sha=None,
    )

    model = webhook_delivery_to_model(entity)
    round_tripped = webhook_delivery_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.delivery_id is None


def test_credential_access_log_round_trip() -> None:
    entity = CredentialAccessLog(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        actor="webhook",
        outcome=CredentialAccessOutcome.USED,
        accessed_at=_NOW,
        scan_task_id=uuid.uuid4(),
        actor_user_id=None,
    )

    model = credential_access_log_to_model(entity)
    round_tripped = credential_access_log_to_entity(model)

    assert round_tripped == entity


def test_credential_access_log_round_trip_manual_actor() -> None:
    entity = CredentialAccessLog(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        actor="manual",
        outcome=CredentialAccessOutcome.DECRYPT_FAILED,
        accessed_at=_NOW,
        scan_task_id=None,
        actor_user_id=uuid.uuid4(),
    )

    model = credential_access_log_to_model(entity)
    round_tripped = credential_access_log_to_entity(model)

    assert round_tripped == entity
    assert round_tripped.scan_task_id is None
