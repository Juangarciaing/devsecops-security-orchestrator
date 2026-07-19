"""`get_finding` use case — single role-redacted finding by id. Powers
`GET /findings/{id}`.

`FindingNotFoundError` is defined HERE (application layer) rather than reused
from `infrastructure.db.repositories.finding_repository.FindingNotFoundError`
— the application layer must not depend on infrastructure (hexagonal
boundary). `suppress_finding`/`unsuppress_finding` import this same class so
a single 404 type covers all 3 by-id use cases.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.value_objects.enums import UserRole


class FindingNotFoundError(Exception):
    """Raised when `finding_id` does not match an existing `Finding`."""


async def get_finding(
    finding_port: FindingPort, finding_id: uuid.UUID, role: UserRole
) -> FindingRead:
    """Return the redacted `FindingRead` matching `finding_id`.

    Raises `FindingNotFoundError` if no `Finding` matches `finding_id`.
    """
    finding = await finding_port.get_by_id(finding_id)
    if finding is None:
        raise FindingNotFoundError(finding_id)

    return redact_finding_for_role(FindingRead.from_entity(finding), role)
