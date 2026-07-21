"""`evaluate_repository_policy` use case — repo-scoped pure threshold over
`FindingPort.open_counts_by_severity` (Module 12a). Powers
`GET /repositories/{id}/policy-check`.

No new port method, no new query, no `ScanRun`/`process_scan.py` touch
(read-time only) — the simplest of the 12-series use cases.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.policy import RepositoryPolicyRead
from orchestrator.application.use_cases.get_repository import get_repository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.services.policy_gate import POLICY_BLOCKING_SEVERITIES, evaluate_policy


async def evaluate_repository_policy(
    repository_port: CodeRepositoryPort,
    finding_port: FindingPort,
    repository_id: uuid.UUID,
) -> RepositoryPolicyRead:
    """Return the pass/fail quality-gate verdict for `repository_id`.

    Raises `RepositoryNotFoundError` if the id does not exist OR the
    repository is soft-deleted — reuses `get_repository`'s existence check,
    the same 404-equivalent semantics as every other repo-scoped endpoint.

    A repository with zero open findings of any severity, or zero scans
    ever recorded, is a well-formed 200 with `verdict="pass"` and an empty
    `violating_counts` — `open_counts_by_severity` returns an empty/sparse
    mapping in both cases, never an error.
    """
    await get_repository(repository_port, repository_id)

    open_counts = await finding_port.open_counts_by_severity(repository_id)
    verdict = evaluate_policy(open_counts)
    blocking_severities = sorted(POLICY_BLOCKING_SEVERITIES)
    violating_counts = {
        severity: open_counts[severity]
        for severity in blocking_severities
        if open_counts.get(severity, 0) > 0
    }

    return RepositoryPolicyRead(
        repository_id=repository_id,
        verdict=verdict,
        blocking_severities=blocking_severities,
        violating_counts=violating_counts,
    )
