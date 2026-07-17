"""Value-object enums must expose the exact reconciled member sets."""

from __future__ import annotations

from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    RepositoryProvider,
    ScannerType,
    ScanRunStatus,
    ScanTaskStatus,
    UserRole,
)


def test_repository_provider_members() -> None:
    assert {member.value for member in RepositoryProvider} == {
        "github",
        "gitlab",
        "bitbucket",
    }


def test_scanner_type_members() -> None:
    assert {member.value for member in ScannerType} == {
        "sast",
        "dast",
        "sca",
        "secrets",
        "iac",
    }


def test_scan_run_status_members() -> None:
    assert {member.value for member in ScanRunStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    }


def test_scan_task_status_members() -> None:
    assert {member.value for member in ScanTaskStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
    }


def test_finding_severity_members() -> None:
    assert {member.value for member in FindingSeverity} == {
        "critical",
        "high",
        "medium",
        "low",
        "info",
    }


def test_finding_status_members() -> None:
    assert {member.value for member in FindingStatus} == {
        "open",
        "resolved",
        "suppressed",
        "false_positive",
    }


def test_user_role_members() -> None:
    assert {member.value for member in UserRole} == {"admin", "member"}
