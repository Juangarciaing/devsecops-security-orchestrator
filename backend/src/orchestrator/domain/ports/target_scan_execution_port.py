"""`TargetScanExecutionPort` — DAST-only execution contract for a `ScanTarget`
subject (dast-scanner design D5, PR5b).

Deliberately a sibling of `ScanExecutionPort`, not a signature change to it:
`ScanExecutionPort.execute(clone_url, ref, ...)` hardcodes the checkout unit
of work across all 5 repository-subject implementations (4 Docker +
`KubernetesSplitScanExecution`). A DAST scan against an arbitrary
`target_url` has no checkout, no ref, and no commit-sha concept at all —
passing a URL as `clone_url` would be semantically wrong, and changing that
signature would cost churn on all 5 implementations for zero benefit.

Framework-free, matching `ScanExecutionPort`: no `docker` SDK import here.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.domain.entities.finding import Finding
    from orchestrator.domain.value_objects.enums import ScannerType


@dataclass(frozen=True, slots=True)
class TargetScanExecutionResult:
    """The parsed outcome of one target-subject scan — no `head_sha`
    (`ScanExecutionResult`'s repository-subject counterpart): a `ScanTarget`
    run has no commit to resolve."""

    findings: list[Finding]


class TargetScanExecutionPort(ABC):
    """Run one DAST scan attempt outside the async database session.

    Sync by design (Module 6 D3, mirrored from `ScanExecutionPort`):
    container orchestration is blocking I/O — callers invoke `.execute()`
    OUTSIDE any asyncio event loop/DB session.
    """

    @abstractmethod
    def execute(
        self,
        target_url: str,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
    ) -> TargetScanExecutionResult:
        """Return the parsed findings for one target-subject scan.

        `target_url` MUST already be validated/authorized by the caller's
        implementation before any container or network resource is created
        (dast-scanner design D3) — this contract does not itself constrain
        when that happens, only that the returned result reflects it.
        """
