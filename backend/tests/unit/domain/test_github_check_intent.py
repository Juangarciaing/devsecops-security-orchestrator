"""`domain.services.github_check_intent` — pure eligibility + bounded payload
building for a `GitHubCheckPublication` intent (github-checks-publisher PR3,
spec: "Atomic Eligible Intent"). Framework-free, no DB needed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.services.github_check_intent import (
    MAX_PAYLOAD_SUMMARY_BYTES,
    build_check_payload_summary,
    github_check_external_id,
    github_check_outcome_for_status,
    is_eligible_for_github_check_publication,
)
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    GitHubCheckOutcome,
    RepositoryProvider,
    ScanRunStatus,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


def _make_finding(severity: FindingSeverity) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        scan_task_id=uuid.uuid4(),
        severity=severity,
        rule_id="rule",
        title="a finding title that must never leak into the payload",
        fingerprint="fp",
        created_at=_NOW,
        updated_at=_NOW,
        file_path="/etc/very/secret/path.py",
        raw_evidence={"token": "ghp_supersecrettoken"},
        snippet="password = 'hunter2'",
    )


# --- Eligibility (task 3.1) --------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "commit_sha", "status", "expected"),
    [
        (RepositoryProvider.GITHUB, "deadbeef", ScanRunStatus.COMPLETED, True),
        # a FAILED aggregate outcome still creates an intent — independent of
        # whether the scan itself succeeded (placeholder ref, unresolved).
        (RepositoryProvider.GITHUB, "main", ScanRunStatus.FAILED, True),
        (RepositoryProvider.GITLAB, "deadbeef", ScanRunStatus.COMPLETED, False),
        (RepositoryProvider.BITBUCKET, "deadbeef", ScanRunStatus.COMPLETED, False),
        # a `ScanTarget`/DAST run's `commit_sha` is always `None`, excluding
        # it here with no separate subject-kind parameter.
        (RepositoryProvider.GITHUB, None, ScanRunStatus.COMPLETED, False),
        (None, None, ScanRunStatus.COMPLETED, False),
        (RepositoryProvider.GITHUB, "deadbeef", ScanRunStatus.PENDING, False),
        (RepositoryProvider.GITHUB, "deadbeef", ScanRunStatus.RUNNING, False),
        (RepositoryProvider.GITHUB, "deadbeef", ScanRunStatus.CANCELLED, False),
    ],
)
def test_eligibility_threshold_table(
    provider: RepositoryProvider | None,
    commit_sha: str | None,
    status: ScanRunStatus,
    expected: bool,
) -> None:
    assert (
        is_eligible_for_github_check_publication(
            provider=provider, commit_sha=commit_sha, status=status
        )
        is expected
    )


# --- Outcome mapping ---------------------------------------------------------


def test_status_outcome_mapping_is_success_for_completed_and_failure_for_failed() -> None:
    assert github_check_outcome_for_status(ScanRunStatus.COMPLETED) is GitHubCheckOutcome.SUCCESS
    assert github_check_outcome_for_status(ScanRunStatus.FAILED) is GitHubCheckOutcome.FAILURE


# --- Bounded, redacted payload summary (task 3.2) ---------------------------


def test_empty_findings_produce_a_zeroed_severity_breakdown() -> None:
    payload = json.loads(build_check_payload_summary([]))

    assert payload["total"] == 0
    assert all(count == 0 for count in payload["by_severity"].values())


def test_payload_reports_a_real_aggregate_count_by_severity() -> None:
    """Triangulation: counts come from actual `Finding.severity` values, not
    a hardcoded shape."""
    findings = [
        _make_finding(FindingSeverity.CRITICAL),
        _make_finding(FindingSeverity.HIGH),
        _make_finding(FindingSeverity.HIGH),
        _make_finding(FindingSeverity.LOW),
    ]

    payload = json.loads(build_check_payload_summary(findings))

    assert payload["total"] == 4
    assert payload["by_severity"]["critical"] == 1
    assert payload["by_severity"]["high"] == 2
    assert payload["by_severity"]["low"] == 1
    assert payload["by_severity"]["medium"] == 0


def test_payload_never_leaks_secrets_raw_evidence_snippets_paths_titles_or_urls() -> None:
    """Threat matrix: none of a `Finding`'s free-text/user-authored fields
    may appear in the payload — only aggregate severity counts."""
    payload = build_check_payload_summary([_make_finding(FindingSeverity.HIGH)])

    assert "hunter2" not in payload
    assert "ghp_supersecrettoken" not in payload
    assert "/etc/very/secret/path.py" not in payload
    assert "a finding title that must never leak into the payload" not in payload
    assert "http" not in payload


def test_scan_error_marker_distinguishes_a_failed_scan_from_a_clean_zero_finding_run() -> None:
    """Without `scan_error=True`, a FAILED scan's payload (always built
    from `findings=[]`, since a failed scan never produces real findings)
    is byte-for-byte identical in shape to a genuinely clean 0-finding
    COMPLETED run — only `outcome` would distinguish them, and only in
    GitHub's own UI, not to any other consumer parsing this payload."""
    clean_run_payload = json.loads(build_check_payload_summary([]))
    failed_scan_payload = json.loads(build_check_payload_summary([], scan_error=True))

    assert "scan_error" not in clean_run_payload
    assert failed_scan_payload["scan_error"] is True
    assert failed_scan_payload["total"] == 0


def test_payload_is_bounded_to_the_fixed_spec_ceiling() -> None:
    payload = build_check_payload_summary(
        [_make_finding(FindingSeverity.HIGH) for _ in range(5000)]
    )

    assert len(payload.encode("utf-8")) <= MAX_PAYLOAD_SUMMARY_BYTES


def test_external_id_is_deterministic_for_the_same_scan_run() -> None:
    """PR5 (design: "GitHub identity") — `external_id` MUST be computed, not
    random, so retries/replays keep resolving the same GitHub-side identity."""
    scan_run_id = uuid.uuid4()

    assert github_check_external_id(scan_run_id) == github_check_external_id(scan_run_id)


def test_external_id_differs_for_different_scan_runs() -> None:
    first = github_check_external_id(uuid.uuid4())
    second = github_check_external_id(uuid.uuid4())

    assert first != second
    assert first.startswith("github-checks:")
