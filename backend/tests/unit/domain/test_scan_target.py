"""ScanTarget domain entity — construction and field invariants.

`ScanTarget` is a wholly independent aggregate (dast-scanner PR1, design D1 /
proposal decision D1-Option B): no `CodeRepository` fields (`provider`,
`owner`, `name` as git identity, `clone_url`, `default_branch`,
`credential_kind`, `credential_ciphertext`) and no linkage to `CodeRepository`
in this slice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.scan_target import ScanTarget


def _make_target(**overrides: object) -> ScanTarget:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "acme-public-site",
        "target_url": "https://example.com",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return ScanTarget(**defaults)  # type: ignore[arg-type]


def test_fields_are_stored_as_provided() -> None:
    target_id = uuid.uuid4()
    now = datetime.now(UTC)

    target = ScanTarget(
        id=target_id,
        name="acme-public-site",
        target_url="https://example.com",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    assert target.id == target_id
    assert target.name == "acme-public-site"
    assert target.target_url == "https://example.com"
    assert target.is_active is True
    assert target.created_at == now
    assert target.updated_at == now


def test_default_is_active_true_when_constructed_via_helper() -> None:
    target = _make_target()

    assert target.is_active is True


def test_is_active_can_be_false() -> None:
    target = _make_target(is_active=False)

    assert target.is_active is False


def test_scan_target_has_no_git_identity_fields() -> None:
    """`ScanTarget` MUST NOT carry any `CodeRepository` git-identity or
    credential fields — this is a new, independent entity, not a
    `CodeRepository` variant (confirmed user decision)."""
    target = _make_target()

    for attr in (
        "provider",
        "owner",
        "clone_url",
        "default_branch",
        "credential_kind",
        "credential_ciphertext",
    ):
        assert not hasattr(target, attr)
