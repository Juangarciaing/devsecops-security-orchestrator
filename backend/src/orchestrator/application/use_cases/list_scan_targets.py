"""`list_scan_targets` use case — returns only active `ScanTarget` rows.

Mirrors `list_repositories.py` (dast-scanner PR6).
"""

from __future__ import annotations

from orchestrator.domain.entities.scan_target import ScanTarget
from orchestrator.domain.ports.scan_target_port import ScanTargetPort


async def list_scan_targets(target_port: ScanTargetPort) -> list[ScanTarget]:
    """Return every active `ScanTarget`. No inactive-filter toggle exists."""
    return await target_port.list_active()
