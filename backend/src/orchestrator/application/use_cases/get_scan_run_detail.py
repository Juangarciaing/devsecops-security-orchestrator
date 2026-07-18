"""`get_scan_run_detail` use case — composes a `ScanRun` + its `ScanTask` + a
findings count for `GET /scans/{id}` (spec: a COUNT, never a findings list).

`FindingCounter` is a structural `Protocol`, not `FindingPort`: `count_by_scan_task`
is deliberately an adapter-only helper on `SqlAlchemyFindingRepository` (PR1
precedent — extend the concrete class, not the abstract contract, when only
one call site needs it). The `Protocol` lets this use case stay framework-light
and independently testable with a fake, without promoting the method onto the
full `FindingPort` abstract contract or coupling to SQLAlchemy directly.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort


class FindingCounter(Protocol):
    """Structural contract for `SqlAlchemyFindingRepository.count_by_scan_task`."""

    async def count_by_scan_task(self, scan_task_id: uuid.UUID) -> int: ...


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

    findings_count = await finding_counter.count_by_scan_task(task.id)
    return run, task, findings_count
