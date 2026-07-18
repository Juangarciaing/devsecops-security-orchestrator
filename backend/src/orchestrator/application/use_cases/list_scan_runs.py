"""`list_scan_runs` use case — paginated `ScanRun` listing.

Thin pass-through to `ScanRunPort.list_paginated` (powers `GET /scans`).
"""

from __future__ import annotations

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.scan_run_port import ScanRunPort


async def list_scan_runs(
    scan_run_port: ScanRunPort, limit: int = 20, offset: int = 0
) -> list[ScanRun]:
    """Return up to `limit` `ScanRun`s (most-recently-created first), skipping `offset`."""
    return await scan_run_port.list_paginated(limit, offset)
