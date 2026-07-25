"""Transport-neutral scan execution contract used by worker orchestration."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.domain.value_objects.enums import ScannerType

if TYPE_CHECKING:
    from orchestrator.domain.entities.finding import Finding


@dataclass(frozen=True, slots=True)
class ScanExecutionResult:
    """The existing checkout-and-parse result without a runtime-specific workspace."""

    head_sha: str
    findings: list[Finding]


class ScanExecutionPort(ABC):
    """Run one scanner attempt outside the async database session."""

    @abstractmethod
    def execute(
        self,
        clone_url: str,
        ref: str,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
    ) -> ScanExecutionResult:
        """Return the resolved commit and parsed findings for one scan."""
