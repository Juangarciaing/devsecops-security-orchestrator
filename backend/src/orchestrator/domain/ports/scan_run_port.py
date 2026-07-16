"""`ScanRunPort` — persistence contract for `ScanRun`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.value_objects.enums import ScanRunStatus


class ScanRunPort(ABC):
    """Async persistence contract for the `ScanRun` aggregate."""

    @abstractmethod
    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        """Return the `ScanRun` with the given id, or `None` if absent."""

    @abstractmethod
    async def list_by_repository(self, repository_id: uuid.UUID) -> list[ScanRun]:
        """Return every `ScanRun` belonging to the given `CodeRepository`."""

    @abstractmethod
    async def create(self, scan_run: ScanRun) -> ScanRun:
        """Persist a new `ScanRun` and return the stored entity."""

    @abstractmethod
    async def update_status(self, scan_run_id: uuid.UUID, status: ScanRunStatus) -> ScanRun:
        """Update the lifecycle `status` of the given `ScanRun` and return it."""
