"""`get_scan_target` use case — treats an inactive target as gone (404-equivalent).

Mirrors `get_repository.py`'s exact shape for `ScanTarget` (dast-scanner PR6).
"""

from __future__ import annotations

import uuid

from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort


class ScanTargetNotFoundError(Exception):
    """Raised when a target id does not exist, or exists but is inactive.

    Shared across `get_scan_target`/`update_scan_target`/`deactivate_scan_target`
    /`trigger_scan` — an inactive target is treated as gone from the API's
    perspective for GET/PATCH/trigger, and as truly missing for DELETE only
    when the id never existed.
    """


async def get_scan_target(target_port: ScanTargetPort, target_id: uuid.UUID) -> ScanTarget:
    """Return the active `ScanTarget` matching `target_id`.

    Raises `ScanTargetNotFoundError` if the id does not exist OR the target
    is soft-deleted (`is_active=False`).
    """
    target = await target_port.get_by_id(target_id)
    if target is None or not target.is_active:
        raise ScanTargetNotFoundError(target_id)
    return target
