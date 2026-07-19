"""`list_scan_findings` use case — paginated, role-redacted findings for one
scan run. Powers `GET /scans/{scan_run_id}/findings`.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import UserRole


class ScanRunNotFoundError(Exception):
    """Raised when `scan_run_id` does not match an existing `ScanRun`."""


async def list_scan_findings(
    scan_run_port: ScanRunPort,
    finding_port: FindingPort,
    scan_run_id: uuid.UUID,
    role: UserRole,
    limit: int = 20,
    offset: int = 0,
) -> list[FindingRead]:
    """Return up to `limit` redacted `FindingRead`s attributed to `scan_run_id`
    (`last_seen_scan_run_id == scan_run_id`), skipping `offset` rows.

    Raises `ScanRunNotFoundError` if no `ScanRun` matches `scan_run_id`.
    Redaction (D8, keyed by `role`) is applied to every finding before return.
    """
    run = await scan_run_port.get_by_id(scan_run_id)
    if run is None:
        raise ScanRunNotFoundError(scan_run_id)

    findings = await finding_port.list_by_last_seen_scan_run(scan_run_id, limit, offset)
    return [redact_finding_for_role(FindingRead.from_entity(finding), role) for finding in findings]
