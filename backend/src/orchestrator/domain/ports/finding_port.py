"""`FindingPort` — persistence contract for `Finding`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus, ScannerType


@dataclass(frozen=True, slots=True)
class FindingTrendBucket:
    """One `ScanRun` bucket returned by `trend_counts_by_first_seen_run`
    (Module 12a) — the EXACT count of findings first observed on that run,
    grouped by `severity`.

    Emitted even for runs that introduced zero findings — in that case
    `severity_counts` is an empty dict. Callers MUST NOT infer a run was
    skipped/filtered from an empty dict; the bucket itself proves the run
    exists and simply introduced nothing (or nothing matching an active
    `scanner_type` filter).
    """

    scan_run_id: uuid.UUID
    occurred_at: datetime
    commit_sha: str
    severity_counts: dict[FindingSeverity, int] = field(default_factory=dict)


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

    @abstractmethod
    async def list_by_last_seen_scan_run(
        self, scan_run_id: uuid.UUID, limit: int, offset: int
    ) -> list[Finding]:
        """Return up to `limit` `Finding`s whose `last_seen_scan_run_id ==
        scan_run_id`, most-recently-created first, skipping `offset` rows.

        Powers `GET /scans/{scan_run_id}/findings` (Module 8 PR2).
        """

    @abstractmethod
    async def list_findings(
        self,
        *,
        severity: FindingSeverity | None = None,
        status: FindingStatus | None = None,
        repository_id: uuid.UUID | None = None,
        scanner_type: ScannerType | None = None,
        limit: int,
        offset: int,
    ) -> list[Finding]:
        """Return up to `limit` `Finding`s matching the given filters (all
        optional, AND-combined), most-recently-created first, skipping
        `offset` rows.

        `scanner_type` requires a join to the owning `ScanTask` (`Finding`
        has no denormalized scanner_type column); implementations MUST only
        perform that join when `scanner_type` is supplied. Powers
        `GET /findings` (Module 8 PR2).
        """

    @abstractmethod
    async def trend_counts_by_first_seen_run(
        self,
        repository_id: uuid.UUID,
        *,
        scanner_type: ScannerType | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[FindingTrendBucket]:
        """Return one `FindingTrendBucket` per completed `ScanRun` belonging to
        `repository_id`, ordered by `ScanRun.created_at` ascending.

        Each bucket carries the EXACT count of `Finding`s whose
        `first_seen_scan_run_id` equals that run, grouped by `severity`.
        `first_seen_scan_run_id` is stamped once at INSERT and never advanced
        on upsert conflict (Module 7 D4), so this is a stable "introduced at
        run R" key — NOT a historical "open as of run R" reconstruction (no
        snapshot table exists or is added by this method).

        Buckets MUST be emitted even for runs that introduced zero matching
        findings (implementations MUST use a LEFT JOIN or equivalent — never
        an INNER JOIN that would silently drop zero-finding runs), so the
        series has no misleading gaps.

        `scanner_type`, when supplied, narrows counted findings to only those
        whose owning `ScanTask.scanner_type` matches — implementations MUST
        apply this as part of the join condition that determines whether a
        `Finding` matches a bucket, NOT as a post-join `WHERE` filter (a
        `WHERE` filter would incorrectly drop the entire bucket/row for a run
        that had ONLY non-matching findings, instead of correctly reporting
        it as zero-matching).

        `date_from`/`date_to` (both optional, inclusive), when supplied,
        narrow to `ScanRun.created_at` within that range. `limit` caps the
        number of DISTINCT scan runs returned (not the number of grouped
        rows), default 100.
        """

    @abstractmethod
    async def open_counts_by_severity(self, repository_id: uuid.UUID) -> dict[FindingSeverity, int]:
        """Return the EXACT count of currently `FindingStatus.OPEN` findings
        for `repository_id`, grouped by `severity`.

        A present-moment snapshot query only (`WHERE status='open' GROUP BY
        severity`) — never an attempt to reconstruct what was open at any
        past point in time (that would require the explicitly-deferred
        per-run snapshot table).
        """
