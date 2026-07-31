"""`update_scan_target` use case — mutable-fields-only PATCH, omitted vs
explicit-null aware.

Mirrors `update_repository.py`'s structure (dast-scanner PR6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from orchestrator.application.dto.scan_target import ScanTargetUpdate
from orchestrator.application.use_cases.get_scan_target import ScanTargetNotFoundError
from orchestrator.application.use_cases.register_scan_target import DuplicateTargetUrlError
from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort
from orchestrator.domain.services.target_url_policy import validate_target_url_shape


class InvalidScanTargetUpdateError(Exception):
    """Raised when `update` explicitly sets a non-nullable field to `null`.

    `name` and `target_url` are NOT NULL on the `ScanTarget` entity — an
    explicit `null` for either is an invalid request, not a legitimate
    "clear this field" request.
    """


async def update_scan_target(
    target_port: ScanTargetPort, target_id: uuid.UUID, update: ScanTargetUpdate
) -> ScanTarget:
    """Apply only the fields explicitly provided in `update` to an active target.

    Uses `model_fields_set` to distinguish "omitted" (leave unchanged) from
    "explicitly set to null" (reject — both fields are NOT NULL).

    Raises `InvalidScanTargetUpdateError` if `name` or `target_url` is
    explicitly set to `null`.

    Raises `ScanTargetNotFoundError` if `target_id` does not exist or the
    target is inactive (soft-deleted).

    A new `target_url` is re-validated via `validate_target_url_shape`
    (design D3) and rejected as `DuplicateTargetUrlError` if it already
    belongs to a different target.
    """
    fields_set = update.model_fields_set
    if "name" in fields_set and update.name is None:
        raise InvalidScanTargetUpdateError("name cannot be null")
    if "target_url" in fields_set and update.target_url is None:
        raise InvalidScanTargetUpdateError("target_url cannot be null")

    target = await target_port.get_by_id(target_id)
    if target is None or not target.is_active:
        raise ScanTargetNotFoundError(target_id)

    if "name" in fields_set:
        target.name = update.name  # type: ignore[assignment]

    if "target_url" in fields_set and update.target_url != target.target_url:
        validate_target_url_shape(update.target_url)  # type: ignore[arg-type]
        existing = await target_port.get_by_url(update.target_url)  # type: ignore[arg-type]
        if existing is not None and existing.id != target_id:
            raise DuplicateTargetUrlError(update.target_url)
        target.target_url = update.target_url  # type: ignore[assignment]

    target.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return await target_port.update(target)
