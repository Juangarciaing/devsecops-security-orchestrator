"""`get_repository_trends` use case — repo-scoped, exact introduced-per-run
(by severity) plus a present-moment current-open snapshot. Powers
`GET /repositories/{id}/trends`.

No per-role redaction (D3): trend aggregates never carry
`Finding.REDACTION_SENSITIVE_FIELDS` (`raw_evidence`, `snippet`, `file_path`,
`line_number`) — only severity-keyed counts — so member and admin callers
receive byte-identical responses. Redaction is intentionally NOT applied here,
unlike `list_findings`/`get_finding`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from orchestrator.application.dto.trends import RepositoryTrendsRead, TrendPoint
from orchestrator.application.use_cases.get_repository import get_repository
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.value_objects.enums import ScannerType


async def get_repository_trends(
    repository_port: CodeRepositoryPort,
    finding_port: FindingPort,
    repository_id: uuid.UUID,
    *,
    scanner_type: ScannerType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
) -> RepositoryTrendsRead:
    """Return the exact trend aggregate for `repository_id`.

    Raises `RepositoryNotFoundError` if the id does not exist OR the
    repository is soft-deleted — reuses `get_repository`'s existence check,
    the same 404-equivalent semantics as every other repo-scoped endpoint.
    """
    await get_repository(repository_port, repository_id)

    buckets = await finding_port.trend_counts_by_first_seen_run(
        repository_id,
        scanner_type=scanner_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    current_open = await finding_port.open_counts_by_severity(repository_id)

    points = [
        TrendPoint(
            scan_run_id=bucket.scan_run_id,
            occurred_at=bucket.occurred_at,
            commit_sha=bucket.commit_sha,
            introduced=bucket.severity_counts,
        )
        for bucket in buckets
    ]
    return RepositoryTrendsRead(
        repository_id=repository_id,
        points=points,
        current_open=current_open,
    )
