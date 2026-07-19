"""WebhookDelivery entity — append-only audit record for one inbound GitHub
webhook HTTP request. `delivery_id` is nullable (absent on rejected/header-less
deliveries — see design D-data-model), so most fields besides `signature_valid`
and `outcome` are optional too (never available before signature verification
or payload parsing succeeds).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.value_objects.enums import WebhookOutcome


def _make_delivery(**overrides: object) -> WebhookDelivery:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "delivery_id": "d1c1-abcd-1234",
        "event_type": "push",
        "source_ip": "192.0.2.10",
        "signature_valid": True,
        "outcome": WebhookOutcome.ACCEPTED,
        "repository_full_name": "acme/widgets",
        "ref": "refs/heads/main",
        "commit_sha": "a" * 40,
        "received_at": now,
    }
    defaults.update(overrides)
    return WebhookDelivery(**defaults)  # type: ignore[arg-type]


def test_fields_are_stored_as_provided() -> None:
    received_at = datetime.now(UTC)
    delivery_id = "abcd-1234"

    delivery = _make_delivery(
        delivery_id=delivery_id,
        event_type="push",
        source_ip="203.0.113.5",
        signature_valid=True,
        outcome=WebhookOutcome.ACCEPTED,
        repository_full_name="acme/widgets",
        ref="refs/heads/main",
        commit_sha="b" * 40,
        received_at=received_at,
    )

    assert delivery.delivery_id == delivery_id
    assert delivery.event_type == "push"
    assert delivery.source_ip == "203.0.113.5"
    assert delivery.signature_valid is True
    assert delivery.outcome == WebhookOutcome.ACCEPTED
    assert delivery.repository_full_name == "acme/widgets"
    assert delivery.ref == "refs/heads/main"
    assert delivery.commit_sha == "b" * 40
    assert delivery.received_at == received_at


def test_delivery_id_can_be_none_for_rejected_signature_deliveries() -> None:
    """A tampered/unsigned request may arrive with no `X-GitHub-Delivery`
    header at all (D-data-model: `delivery_id` is nullable, not required for
    the audit row to exist)."""
    delivery = _make_delivery(
        delivery_id=None,
        signature_valid=False,
        outcome=WebhookOutcome.REJECTED_SIGNATURE,
        repository_full_name=None,
        ref=None,
        commit_sha=None,
    )

    assert delivery.delivery_id is None
    assert delivery.signature_valid is False
    assert delivery.outcome == WebhookOutcome.REJECTED_SIGNATURE


def test_entity_has_no_updated_at_field() -> None:
    """Append-only audit row: written once, never mutated."""
    field_names = {f.name for f in dataclasses.fields(WebhookDelivery)}

    assert "updated_at" not in field_names
    assert "received_at" in field_names
