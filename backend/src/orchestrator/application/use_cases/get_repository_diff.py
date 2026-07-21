"""`get_repository_diff` use case — repo-scoped, exact ADDED/RESOLVED/CARRIED
finding partition between the latest completed `ScanRun` and the run
immediately before it. Powers `GET /repositories/{id}/diff`.

Unlike `get_repository_trends` (aggregate counts only, D3: no redaction),
diff bodies carry full per-finding sensitive fields, so every returned
finding is passed through `redact_finding_for_role`, exactly as
`list_scan_findings`/`list_findings` do.
"""

from __future__ import annotations

import uuid

from orchestrator.application.dto.diff import RepositoryDiffRead, RunRef
from orchestrator.application.dto.finding import FindingRead
from orchestrator.application.security.redaction import redact_finding_for_role
from orchestrator.application.use_cases.get_repository import get_repository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.value_objects.enums import UserRole


def _run_ref(run: ScanRun) -> RunRef:
    return RunRef(scan_run_id=run.id, occurred_at=run.created_at, commit_sha=run.commit_sha)


def _redacted(findings: list[Finding], role: UserRole) -> list[FindingRead]:
    return [redact_finding_for_role(FindingRead.from_entity(finding), role) for finding in findings]


async def get_repository_diff(
    repository_port: CodeRepositoryPort,
    scan_run_port: ScanRunPort,
    finding_port: FindingPort,
    repository_id: uuid.UUID,
    role: UserRole,
) -> RepositoryDiffRead:
    """Return the exact latest-vs-immediately-previous finding diff for
    `repository_id`, with every finding in `added`/`resolved`/`carried`
    redacted per `role` (design's per-finding redaction requirement — unlike
    `get_repository_trends`'s role-agnostic aggregate counts).

    Raises `RepositoryNotFoundError` if the id does not exist OR the
    repository is soft-deleted — reuses `get_repository`'s existence check,
    the same 404-equivalent semantics as every other repo-scoped endpoint.

    Fewer than 2 completed runs is a normal, non-error 200 shape (design D4):

    - 0 completed runs: `latest_run`/`baseline_run` both `None`, all three
      sets empty.
    - Exactly 1 completed run: `baseline_run` is `None`; `added` contains
      every finding introduced by that sole run; `resolved`/`carried` are
      empty BY DEFINITION — there is no baseline to compare against, so
      these two categories are meaningless here, not merely coincidentally
      empty. A fresh random UUID (guaranteed to never match a real
      `ScanRun.id`) is passed as `diff_between_runs`'s `baseline_run_id` to
      isolate its `added` predicate cleanly, without adding a second query
      method just for this one-run edge case; the returned `resolved`/
      `carried` from that call are deliberately discarded/overridden to `[]`
      rather than trusted, keeping the "no baseline" contract exact.
    """
    await get_repository(repository_port, repository_id)

    recent_runs = await scan_run_port.list_recent_completed(repository_id, limit=2)

    if not recent_runs:
        return RepositoryDiffRead(
            repository_id=repository_id,
            latest_run=None,
            baseline_run=None,
            added=[],
            resolved=[],
            carried=[],
        )

    latest = recent_runs[0]

    if len(recent_runs) == 1:
        diff = await finding_port.diff_between_runs(repository_id, latest.id, uuid.uuid4())
        return RepositoryDiffRead(
            repository_id=repository_id,
            latest_run=_run_ref(latest),
            baseline_run=None,
            added=_redacted(diff.added, role),
            resolved=[],
            carried=[],
        )

    baseline = recent_runs[1]
    diff = await finding_port.diff_between_runs(repository_id, latest.id, baseline.id)
    return RepositoryDiffRead(
        repository_id=repository_id,
        latest_run=_run_ref(latest),
        baseline_run=_run_ref(baseline),
        added=_redacted(diff.added, role),
        resolved=_redacted(diff.resolved, role),
        carried=_redacted(diff.carried, role),
    )
