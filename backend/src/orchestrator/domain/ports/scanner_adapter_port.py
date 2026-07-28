"""`ScannerAdapterPort` — contract for one security-scanner tool adapter
(Module 7 D1).

Framework-free: this module MUST NOT import SQLAlchemy, Pydantic, or the
`docker` SDK — only concrete adapters (e.g.
`infrastructure.scanners.gitleaks_adapter.GitleaksAdapter`) do that.

Synchronous by design, matching `ContainerRunnerPort` (Module 6 D3):
container orchestration is blocking I/O and callers invoke `.parse()`
OUTSIDE any async DB session/event loop.

`scan_task_id` stays on `parse()` (D1, minimal/honest): it stamps the
producing task on every `Finding`, which is non-optional on the entity.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.domain.entities.finding import Finding
    from orchestrator.domain.ports.container_runner_port import RunResult
    from orchestrator.domain.value_objects.enums import ScannerType


class ScannerAdapterPort(ABC):
    """Contract implemented by one scanner-tool adapter (Gitleaks, ...).

    A descriptor executor (`infrastructure.container.scan_execution_factory`)
    selects and drives the concrete implementation for a given `ScannerType`;
    the container invocation itself is fixed argv on the descriptor, not on
    this adapter (compat `scan(volume_name)` was removed once the descriptor
    executors became the only production callers — Module 13c PR5c).
    """

    @abstractmethod
    def parse(self, result: RunResult, scan_task_id: uuid.UUID) -> list[Finding]:
        """Interpret one `RunResult` into the `Finding`s it represents.

        Zero findings on a clean scan is a valid, successful outcome —
        returns `[]`, not an error. A genuine tool failure raises an
        adapter-specific exception (never conflated with "no findings").
        """

    @abstractmethod
    def supports(self, scanner_type: ScannerType) -> bool:
        """Return whether this adapter handles the given `ScannerType`."""
