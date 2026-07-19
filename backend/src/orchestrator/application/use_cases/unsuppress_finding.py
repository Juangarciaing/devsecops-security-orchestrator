"""`unsuppress_finding` use case — transitions a `Finding` back to `OPEN` via
the pure `domain.services.finding_transitions.unsuppress` FSM. Powers
`POST /findings/{id}/unsuppress`.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.application.use_cases.get_finding import FindingNotFoundError
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.services.finding_transitions import unsuppress
from orchestrator.domain.value_objects.enums import UserRole


async def unsuppress_finding(
    finding_port: FindingPort, finding_id: uuid.UUID, role: UserRole
) -> FindingRead:
    """Transition `finding_id` to `OPEN`.

    `SUPPRESSED -> OPEN` persists via `FindingPort.update_status`.
    `OPEN -> OPEN` is an idempotent no-op: the current finding is returned
    WITHOUT a write (no `updated_at` bump).

    Raises `FindingNotFoundError` if `finding_id` does not exist,
    `IllegalStatusTransitionError` (409-mapped at the router layer, PR3) if
    the finding's current status is outside `{OPEN, SUPPRESSED}`. Redaction
    (D8, keyed by `role`) is applied to the returned finding either way.
    """
    finding = await finding_port.get_by_id(finding_id)
    if finding is None:
        raise FindingNotFoundError(finding_id)

    resulting_status = unsuppress(finding.status)
    if resulting_status == finding.status:
        return redact_finding_for_role(FindingRead.from_entity(finding), role)

    updated = await finding_port.update_status(finding_id, resulting_status)
    return redact_finding_for_role(FindingRead.from_entity(updated), role)
