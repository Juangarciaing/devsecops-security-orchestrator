"""`register_scan_target` use case — rejects a duplicate `target_url`,
active or soft-deleted, and validates the URL's shape before persisting.

Mirrors `register_repository.py`'s structure (dast-scanner PR6, design D3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort
from orchestrator.domain.services.target_url_policy import validate_target_url_shape


class DuplicateTargetUrlError(Exception):
    """Raised when `target_url` already exists, active or not.

    `target_url` is `ScanTarget`'s natural dedup key (its docstring/unique
    constraint) — there is no compound identity tuple like `CodeRepository`'s
    `(provider, owner, name)`.
    """


async def register_scan_target(
    target_port: ScanTargetPort, name: str, target_url: str
) -> ScanTarget:
    """Create and persist a new `ScanTarget`, always starting `is_active=True`.

    Raises `InvalidTargetUrlError` (propagated from `validate_target_url_shape`,
    design D3) if `target_url`'s shape is malformed or an obviously-private
    literal — registration-time UX validation only, not the load-bearing SSRF
    control (that is `dns_target_resolver.resolve_and_authorize`, re-run
    immediately before every scan launch).

    Raises `DuplicateTargetUrlError` if `target_url` already exists, whether
    the existing match is active or soft-deleted — reactivation is out of
    scope for this module, mirroring `register_repository`'s identity check.
    """
    validate_target_url_shape(target_url)

    existing = await target_port.get_by_url(target_url)
    if existing is not None:
        raise DuplicateTargetUrlError(target_url)

    now = datetime.now(UTC).replace(tzinfo=None)
    target = ScanTarget(
        id=uuid.uuid4(),
        name=name,
        target_url=target_url,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    return await target_port.create(target)
