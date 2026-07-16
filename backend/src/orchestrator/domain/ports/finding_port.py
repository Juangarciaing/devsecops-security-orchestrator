"""`FindingPort` — persistence contract for `Finding`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingStatus


class FindingPort(ABC):
    """Async persistence contract for the `Finding` aggregate."""

    @abstractmethod
    async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
        """Return the `Finding` with the given id, or `None` if absent."""

    @abstractmethod
    async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
        """Return every `Finding` belonging to the given `ScanTask`."""

    @abstractmethod
    async def create(self, finding: Finding) -> Finding:
        """Persist a new `Finding` and return the stored entity."""

    @abstractmethod
    async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
        """Update the triage `status` of the given `Finding` and return it."""
