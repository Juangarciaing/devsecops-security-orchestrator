"""`deactivate_scan_target` use case — idempotent soft-delete.

Mirrors `deactivate_repository.py`'s structure (dast-scanner PR6).
"""

from __future__ import annotations

import uuid

from orchestrator.application.use_cases.get_scan_target import ScanTargetNotFoundError
from orchestrator.domain.ports.scan_target_port import ScanTargetPort


async def deactivate_scan_target(target_port: ScanTargetPort, target_id: uuid.UUID) -> None:
    """Soft-delete the `ScanTarget` matching `target_id`.

    Raises `ScanTargetNotFoundError` only if `target_id` truly does not
    exist. Deactivating an already-inactive target is an idempotent no-op
    success — it never raises.
    """
    target = await target_port.get_by_id(target_id)
    if target is None:
        raise ScanTargetNotFoundError(target_id)
    await target_port.soft_delete(target_id)
