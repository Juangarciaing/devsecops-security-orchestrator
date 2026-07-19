"""`list_findings` use case — cross-run filtered, role-redacted, paginated
findings. Powers `GET /findings`.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.value_objects.enums import (
    FindingSeverity,
    FindingStatus,
    ScannerType,
    UserRole,
)


async def list_findings(
    finding_port: FindingPort,
    role: UserRole,
    *,
    severity: FindingSeverity | None = None,
    status: FindingStatus | None = None,
    repository_id: uuid.UUID | None = None,
    scanner_type: ScannerType | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[FindingRead]:
    """Return up to `limit` redacted `FindingRead`s matching the given filters
    (all optional, AND-combined), skipping `offset` rows.

    Redaction (D8, keyed by `role`) is applied to every finding before return.
    """
    findings = await finding_port.list_findings(
        severity=severity,
        status=status,
        repository_id=repository_id,
        scanner_type=scanner_type,
        limit=limit,
        offset=offset,
    )
    return [redact_finding_for_role(FindingRead.from_entity(finding), role) for finding in findings]
