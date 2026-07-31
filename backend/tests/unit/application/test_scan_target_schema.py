"""ScanTargetRead/Create/Update schema — round-trip and validation.

Mirrors `test_code_repository_schema.py`'s shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.scan_target import (
    ScanTargetCreate,
    ScanTargetRead,
    ScanTargetUpdate,
)
from orchestrator.domain.entities.scan_target import ScanTarget


def _make_entity(**overrides: object) -> ScanTarget:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "acme-public-site",
        "target_url": "https://public.example.com",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return ScanTarget(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_all_fields() -> None:
    entity = _make_entity()

    schema = ScanTargetRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.is_active is True


def test_round_trip_preserves_all_fields_with_different_values() -> None:
    entity = _make_entity(
        name="other-target",
        target_url="https://other.example.com",
        is_active=False,
    )

    schema = ScanTargetRead.from_entity(entity)
    round_tripped = schema.to_entity()

    assert round_tripped == entity
    assert schema.is_active is False


def test_scan_target_create_accepts_name_and_target_url() -> None:
    create = ScanTargetCreate(name="acme", target_url="https://acme.example.com")

    assert create.name == "acme"
    assert create.target_url == "https://acme.example.com"


def test_scan_target_update_fields_all_optional() -> None:
    update = ScanTargetUpdate()

    assert update.name is None
    assert update.target_url is None
