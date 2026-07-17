"""`redact_finding_for_role` (D8) — pure, role-aware `Finding` redaction.

A pure `FindingRead -> FindingRead` function with no HTTP/DB dependency, so
any caller (Module 8's router layer today; anywhere else tomorrow) reuses the
same masking rule uniformly. Masks exactly `Finding.REDACTION_SENSITIVE_FIELDS`.
"""

from __future__ import annotations

from orchestrator.application.dto.finding import FindingRead
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import UserRole


def redact_finding_for_role(finding: FindingRead, role: UserRole) -> FindingRead:
    """Return a copy of `finding` with sensitive fields masked for non-admin roles.

    Admins receive the finding untouched. Any other role has every field in
    `Finding.REDACTION_SENSITIVE_FIELDS` set to `None`.
    """
    if role is UserRole.ADMIN:
        return finding.model_copy()

    masked = dict.fromkeys(Finding.REDACTION_SENSITIVE_FIELDS, None)
    return finding.model_copy(update=masked)
