"""Canonical value-object enums for the domain layer.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.
"""

from __future__ import annotations

from enum import StrEnum


class RepositoryProvider(StrEnum):
    """Source-control hosting provider for a `CodeRepository`."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


class ScannerType(StrEnum):
    """Kind of security scanner a `ScanTask` runs."""

    SAST = "sast"
    DAST = "dast"
    SCA = "sca"
    SECRETS = "secrets"
    IAC = "iac"


class ScanRunStatus(StrEnum):
    """Lifecycle status of a whole `ScanRun`."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanTaskStatus(StrEnum):
    """Lifecycle status of a single `ScanTask` within a `ScanRun`."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FindingSeverity(StrEnum):
    """Severity classification of a `Finding`."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(StrEnum):
    """Triage status of a `Finding`."""

    OPEN = "open"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    FALSE_POSITIVE = "false_positive"


class UserRole(StrEnum):
    """RBAC role assigned to a `User`."""

    ADMIN = "admin"
    MEMBER = "member"


class WebhookOutcome(StrEnum):
    """Result of processing one inbound `WebhookDelivery` (Module 10 D3).

    The `IngestWebhookUseCase` records exactly one of these for every
    delivery, whether or not a scan was ultimately triggered.
    """

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED_SIGNATURE = "rejected_signature"
    IGNORED_EVENT = "ignored_event"
    INVALID_PAYLOAD = "invalid_payload"
    IGNORED_UNKNOWN_REPO = "ignored_unknown_repo"
    IGNORED_INACTIVE_REPO = "ignored_inactive_repo"
    IGNORED_NON_DEFAULT_BRANCH = "ignored_non_default_branch"
