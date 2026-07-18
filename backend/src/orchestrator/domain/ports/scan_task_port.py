"""`ScanTaskPort` — persistence contract for `ScanTask`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.value_objects.enums import ScannerType, ScanTaskStatus


class ScanTaskPort(ABC):
    """Async persistence contract for the `ScanTask` aggregate."""

    @abstractmethod
    async def get_by_id(self, scan_task_id: uuid.UUID) -> ScanTask | None:
        """Return the `ScanTask` with the given id, or `None` if absent."""

    @abstractmethod
    async def list_by_scan_run(self, scan_run_id: uuid.UUID) -> list[ScanTask]:
        """Return every `ScanTask` belonging to the given `ScanRun`."""

    @abstractmethod
    async def create(self, scan_task: ScanTask) -> ScanTask:
        """Persist a new `ScanTask` and return the stored entity.

        Callers MUST check `ScanTask.conflicts_with()` against existing tasks
        for the same `scan_run_id` before calling this — the
        `(scan_run_id, scanner_type)` uniqueness is enforced at the DB level.
        """

    @abstractmethod
    async def update_status(self, scan_task_id: uuid.UUID, status: ScanTaskStatus) -> ScanTask:
        """Update the lifecycle `status` of the given `ScanTask` and return it."""

    @abstractmethod
    async def find_active_task(
        self, repository_id: uuid.UUID, commit_sha: str, scanner_type: ScannerType
    ) -> ScanTask | None:
        """Return an in-flight `ScanTask` for `(repository_id, commit_sha, scanner_type)`.

        "In-flight" means the task's `status` is `PENDING` or `RUNNING` — a
        `COMPLETED`/`FAILED`/`SKIPPED` task never blocks a fresh trigger.
        Returns `None` if no such task exists. Matching spans both aggregates:
        `repository_id`/`commit_sha` live on the owning `ScanRun`, while
        `scanner_type` lives on the `ScanTask` itself (D3).
        """
