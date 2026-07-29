"""Orphaned Job/PVC reconciliation sweep (Module 13c PR8, spec's
"Deterministic PVC Lifecycle and Observability" — "reconciliation MUST
remove orphans").

`KubernetesSplitScanExecution`'s own get-before-create idempotency already
handles the common case (a Celery redelivery after a worker crash discovers
and reuses whatever the prior attempt created). This module covers the
remaining case: a scan that is NEVER redelivered (e.g. its `ScanTask` was
independently marked terminal, or Celery's retry budget was exhausted)
still leaves its Job/PVC behind forever without a sweep.

This routine only ever DELETES — it never creates, retries, or otherwise
runs a scan; Celery remains the sole retry authority (spec's "Bounded
Result Transport and Failure Semantics"). `active_names` MUST be supplied
by the caller (typically derived from the `ScanTask` table's currently
RUNNING rows' bounded names) — never inferred from cluster state alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.infrastructure.observability.metrics import (
    record_kubernetes_reconciliation,
)

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_job_runner_port import KubernetesJobRunnerPort


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Names actually deleted by one sweep — empty on a clean namespace."""

    deleted_job_names: tuple[str, ...]
    deleted_pvc_names: tuple[str, ...]


def reconcile_orphaned_kubernetes_resources(
    runner: KubernetesJobRunnerPort,
    *,
    namespace: str,
    active_names: set[str],
) -> ReconciliationReport:
    """Delete every Job/PVC in `namespace` whose name is NOT in
    `active_names`. Idempotent: `delete_job`/`delete_pvc` are no-ops when the
    resource is already absent (PR6), so running this twice in a row deletes
    nothing further the second time.
    """
    deleted_jobs = tuple(
        name for name in runner.list_job_names(namespace) if name not in active_names
    )
    for name in deleted_jobs:
        runner.delete_job(namespace, name)

    deleted_pvcs = tuple(
        name for name in runner.list_pvc_names(namespace) if name not in active_names
    )
    for name in deleted_pvcs:
        runner.delete_pvc(namespace, name)

    record_kubernetes_reconciliation(len(deleted_jobs), len(deleted_pvcs))
    return ReconciliationReport(deleted_job_names=deleted_jobs, deleted_pvc_names=deleted_pvcs)
