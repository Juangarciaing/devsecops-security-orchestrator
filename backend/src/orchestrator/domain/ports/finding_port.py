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

    @abstractmethod
    async def bulk_upsert_findings(
        self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
    ) -> None:
        """DB-atomically insert-or-update `findings` for one scan pass.

        Dedup key is `(repository_id, fingerprint)` (Module 7 D4). On INSERT
        (no existing row for that key): stamps `repository_id` and
        `first_seen_scan_run_id = last_seen_scan_run_id = scan_run_id`. On
        CONFLICT (an existing row already has that key): advances ONLY
        `last_seen_scan_run_id` (and `updated_at`) — every other field,
        including `status`, is left untouched, so a suppressed finding stays
        suppressed across re-scans.

        MUST be race-safe under concurrent calls for the same
        `(repository_id, fingerprint)` — implementations MUST use a
        DB-atomic upsert (e.g. `INSERT ... ON CONFLICT ... DO UPDATE`), never
        a read-then-write check (TOCTOU race under concurrent same-repo
        scans).
        """

    @abstractmethod
    async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
        """Return the count of `Finding`s whose `last_seen_scan_run_id == scan_run_id`.

        Powers the redefined `GET /scans/{id}` findings count (Module 7 D5):
        counts findings currently attributed to this run — whether first
        introduced by it or merely re-observed on it — not findings
        physically produced by this run's `ScanTask` (that was the old,
        replaced `count_by_scan_task` semantics).
        """
