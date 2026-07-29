"""CredentialAccessLog entity — append-only audit record, no `updated_at`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.credential_access_log import CredentialAccessLog
from orchestrator.domain.value_objects.enums import CredentialAccessOutcome, CredentialKind


def test_credential_access_log_fields_are_stored_as_provided() -> None:
    log_id = uuid.uuid4()
    repository_id = uuid.uuid4()
    scan_task_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()
    accessed_at = datetime.now(UTC)

    entry = CredentialAccessLog(
        id=log_id,
        repository_id=repository_id,
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        actor="manual",
        outcome=CredentialAccessOutcome.USED,
        accessed_at=accessed_at,
        scan_task_id=scan_task_id,
        actor_user_id=actor_user_id,
    )

    assert entry.id == log_id
    assert entry.repository_id == repository_id
    assert entry.credential_kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert entry.actor == "manual"
    assert entry.outcome is CredentialAccessOutcome.USED
    assert entry.accessed_at == accessed_at
    assert entry.scan_task_id == scan_task_id
    assert entry.actor_user_id == actor_user_id


def test_credential_access_log_defaults_scan_task_id_and_actor_user_id_to_none() -> None:
    """A webhook-triggered access has no authenticated actor; a decrypt
    attempted outside a scan task has no `scan_task_id`."""
    entry = CredentialAccessLog(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        actor="webhook",
        outcome=CredentialAccessOutcome.SEALED,
        accessed_at=datetime.now(UTC),
    )

    assert entry.scan_task_id is None
    assert entry.actor_user_id is None


def test_credential_access_log_has_no_updated_at_attribute() -> None:
    """Append-only design: this row is written once and never mutated."""
    entry = CredentialAccessLog(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        credential_kind=CredentialKind.PERSONAL_ACCESS_TOKEN,
        actor="webhook",
        outcome=CredentialAccessOutcome.KEY_UNAVAILABLE,
        accessed_at=datetime.now(UTC),
    )

    assert not hasattr(entry, "updated_at")
