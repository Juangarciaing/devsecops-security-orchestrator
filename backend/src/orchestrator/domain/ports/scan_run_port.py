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

    @abstractmethod
    async def list_paginated(self, limit: int, offset: int) -> list[ScanRun]:
        """Return up to `limit` `ScanRun`s, most-recently-created first, skipping `offset` rows.

        Powers `GET /scans` (design deviation #7: the list endpoint was never
        paginated before this module).
        """

    @abstractmethod
    async def list_recent_completed(self, repository_id: uuid.UUID, limit: int) -> list[ScanRun]:
        """Return up to `limit` `ScanRun`s for `repository_id` with
        `status == ScanRunStatus.COMPLETED`, ordered `created_at DESC, id DESC`.

        Powers `GET /repositories/{id}/diff` (Module 12b): the diff's
        `latest`/`baseline` runs are the first two entries of
        `list_recent_completed(repository_id, limit=2)`.

        `id` is a random `uuid4` (Module 2), never monotonic — `created_at`
        (server `now()`) is the real ordering key; `id` is only a
        deterministic tiebreak for the astronomically unlikely case of two
        runs sharing the same `created_at`, mirroring the `(created_at, id)`
        convention already used by `list_by_last_seen_scan_run`/`list_findings`.
        """
