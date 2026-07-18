"""`get_scan_run_detail` use case — composes a `ScanRun` + its `ScanTask` + a
findings count for `GET /scans/{id}` (spec: a COUNT, never a findings list).

Module 7 D5 redefines the count: `count_by_last_seen_scan_run(scan_run_id)`
(counts findings currently attributed to this run — first-seen OR re-observed
on it) replaces the old `count_by_scan_task(task.id)` (findings physically
produced by this run's `ScanTask`). Unlike PR1/PR2's `count_by_scan_task`
precedent, `count_by_last_seen_scan_run` IS also promoted onto the abstract
`FindingPort` (Module 7 PR3, D4/D5) — cross-run dedup counting is now a core
port concern. `FindingCounter` stays a structural `Protocol` here regardless:
it lets this use case stay framework-light and independently testable with a
fake, without coupling to `FindingPort`/SQLAlchemy directly.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort


class FindingCounter(Protocol):
    """Structural contract for `FindingPort.count_by_last_seen_scan_run`."""

    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int: ...


class ScanRunNotFoundError(Exception):
    """Raised when a `ScanRun` id does not exist (404-equivalent for `GET /scans/{id}`)."""


async def get_scan_run_detail(
    scan_run_port: ScanRunPort,
    scan_task_port: ScanTaskPort,
    finding_counter: FindingCounter,
    scan_run_id: uuid.UUID,
) -> tuple[ScanRun, ScanTask, int]:
    """Return `(run, task, findings_count)` for `scan_run_id`.

    Raises `ScanRunNotFoundError` if no `ScanRun` matches `scan_run_id`.
    This module only ever creates one `ScanTask` per `ScanRun` (SECRETS-only
    skeleton, D3) — a missing task on an existing run is a data-integrity
    violation and raises `RuntimeError`, not `ScanRunNotFoundError`.
    """
    run = await scan_run_port.get_by_id(scan_run_id)
    if run is None:
        raise ScanRunNotFoundError(scan_run_id)

    tasks = await scan_task_port.list_by_scan_run(scan_run_id)
    if not tasks:
        raise RuntimeError(f"data integrity violation: ScanRun {scan_run_id} has no ScanTask")
    task = tasks[0]

    findings_count = await finding_counter.count_by_last_seen_scan_run(run.id)
    return run, task, findings_count
