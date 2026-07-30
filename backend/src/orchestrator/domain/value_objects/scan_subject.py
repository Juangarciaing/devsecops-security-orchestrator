"""Polymorphic subject of a scan run or finding."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class ScanSubjectKind(StrEnum):
    """Supported scan subject aggregates."""

    REPOSITORY = "repository"
    SCAN_TARGET = "scan_target"


class InvalidScanSubjectError(ValueError):
    """Raised when a subject has both IDs or neither ID."""


@dataclass(frozen=True, slots=True)
class ScanSubject:
    """The exactly-one repository or scan-target subject identity."""

    kind: ScanSubjectKind
    id: uuid.UUID

    @classmethod
    def from_columns(
        cls, repository_id: uuid.UUID | None, scan_target_id: uuid.UUID | None
    ) -> ScanSubject:
        """Construct a subject from its nullable persistence columns."""
        if (repository_id is None) == (scan_target_id is None):
            raise InvalidScanSubjectError("exactly one scan subject ID must be set")
        if repository_id is not None:
            return cls(ScanSubjectKind.REPOSITORY, repository_id)
        assert scan_target_id is not None
        return cls(ScanSubjectKind.SCAN_TARGET, scan_target_id)

    @property
    def repository_id(self) -> uuid.UUID | None:
        """Repository identity when this is a repository subject."""
        return self.id if self.kind is ScanSubjectKind.REPOSITORY else None

    @property
    def scan_target_id(self) -> uuid.UUID | None:
        """Scan target identity when this is a target subject."""
        return self.id if self.kind is ScanSubjectKind.SCAN_TARGET else None
