"""Pure `GitHubCheckPublication` intent eligibility + bounded payload
building (github-checks-publisher PR3, design: "Atomic Eligible Intent").

Framework-free: MUST NOT import SQLAlchemy/Pydantic, and MUST NOT touch the
separate quality-gate pass/fail evaluation (`domain.services.policy_gate`) —
outcome here mirrors the `ScanRun` aggregate's own lifecycle status only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    GitHubCheckOutcome,
    RepositoryProvider,
    ScanRunStatus,
)

#: One logical Check Run per `scan_run_id` — the DB `UNIQUE(scan_run_id,
#: check_name)` constraint (PR1) backs "Single Logical Check Run" identity.
GITHUB_CHECK_NAME = "security/orchestrator"

_ELIGIBLE_TERMINAL_STATUSES = frozenset({ScanRunStatus.COMPLETED, ScanRunStatus.FAILED})

#: Fixed payload ceiling (spec: ~4 KiB) — a hard ceiling, never a soft target.
MAX_PAYLOAD_SUMMARY_BYTES = 4096


def is_eligible_for_github_check_publication(
    *, provider: RepositoryProvider | None, commit_sha: str | None, status: ScanRunStatus
) -> bool:
    """Eligible only when `provider` is `GITHUB`, `commit_sha` is non-empty
    (a `ScanTarget`/DAST run's `commit_sha` is always `None`, excluding it
    with no separate subject-kind check), and `status` is a terminal
    aggregate outcome — `FAILED` still creates an intent; only delivery
    (PR4/5) depends on the scan itself having succeeded."""
    if provider is not RepositoryProvider.GITHUB:
        return False
    if not commit_sha:
        return False
    return status in _ELIGIBLE_TERMINAL_STATUSES


def github_check_external_id(scan_run_id: uuid.UUID) -> str:
    """Deterministic (NEVER random) GitHub-side dedup identity for one scan
    run's Check Run (design: "GitHub identity", PR5) — the same
    `scan_run_id` always yields the same `external_id`, so a retried or
    replayed publish resolves to the same logical Check Run."""
    return f"github-checks:{scan_run_id}"


def github_check_outcome_for_status(status: ScanRunStatus) -> GitHubCheckOutcome:
    """Map a terminal `ScanRunStatus` to its Check Run conclusion. Callers
    MUST only pass an already-eligible status (`COMPLETED`/`FAILED`)."""
    if status is ScanRunStatus.COMPLETED:
        return GitHubCheckOutcome.SUCCESS
    return GitHubCheckOutcome.FAILURE


def build_check_payload_summary(findings: Sequence[Finding], *, scan_error: bool = False) -> str:
    """Bounded, redacted, aggregate summary (spec: ~4 KiB ceiling): a total
    count plus a per-severity breakdown, derived from `Finding.severity`
    alone. NEVER includes secrets, raw evidence, snippets, file paths,
    titles/URLs, or arbitrary user-authored Markdown.

    `scan_error=True` (a `FAILED` scan, which never has real findings —
    callers always pass `findings=[]` alongside it) adds an explicit
    `"scan_error": true` marker. Without it, a FAILED scan's payload would
    be byte-for-byte identical in shape to a genuinely clean 0-finding
    run (`{"total": 0, "by_severity": {...all zero}}`) — `outcome:
    FAILURE` is visible in GitHub's own Check Run UI, but any OTHER
    consumer parsing just this payload (a downstream integration, a
    dashboard) would otherwise have no signal that no findings were ever
    actually produced."""
    counts: dict[str, int] = {severity.value: 0 for severity in FindingSeverity}
    for finding in findings:
        counts[finding.severity.value] += 1
    body: dict[str, object] = {"total": len(findings), "by_severity": counts}
    if scan_error:
        body["scan_error"] = True
    payload = json.dumps(body, sort_keys=True)
    return payload[:MAX_PAYLOAD_SUMMARY_BYTES]
