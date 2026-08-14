"""Celery application instance for the orchestrator's async worker layer.

Resolves broker/backend URLs from `Settings` at import time (D1) — the
standard `celery -A orchestrator.workers.celery_app worker` pattern requires
a fully-configured module-level `celery_app` object. `celery_broker_url` /
`celery_result_backend` take priority when set; otherwise both fall back to
`Settings.redis_url` (Module 1, frozen).

Declares two queues: `scan` (consumed by the worker once Module 5 PR2's
no-op task exists) and `webhook` (configured but unconsumed — reserved for
Module 10). Routes the not-yet-implemented `process_scan_task` onto `scan`
by its fully-qualified task name; Celery's `task_routes` is a static routing
table and does not require the task to be registered at config time.

Sets `include=[...]` so a standalone worker process (started via
`celery -A orchestrator.workers.celery_app worker`, which only ever imports
THIS module) also imports `orchestrator.workers.tasks.process_scan` and
registers `process_scan_task` on its own app instance. Without this, only
the backend/API process (via the router's separate, lazy, request-time
import of that same module — see `api/v1/routers/scans.py`) ever registers
the task; the worker process's task registry stays empty and it silently
discards every real message with `Received unregistered task of type
'...'`. Confirmed via a live `docker compose up` end-to-end run — see
`sdd/module-5-scan-orchestration-skeleton/verify-report`.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue

from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.kubernetes.backend_selection import (
    ensure_scan_execution_backend_available,
)
from orchestrator.infrastructure.observability.metrics import (
    start_worker_heartbeat,
    stop_worker_heartbeat,
)
from orchestrator.infrastructure.observability.tracing import (
    configure_tracing,
    instrument_celery,
    shutdown_tracing,
)

_settings = get_settings()

# Module 13c PR8 (spec's "Explicit Backend Selection"): runs at IMPORT time,
# deliberately BEFORE `Celery(...)` below — not inside a `worker_process_init`
# signal handler, since Celery's `Signal.send()` catches and logs receiver
# exceptions rather than propagating them (see
# `backend_selection.ensure_scan_execution_backend_available`'s docstring).
# This is the earliest possible point that fails startup before any scan
# work runs, for every process that imports this module (a real
# `celery -A ... worker`, and the API's lazy import in `api/v1/routers/scans.py`).
ensure_scan_execution_backend_available(_settings)

# github-checks-publisher PR4 (design: "Dispatch and lease") — the Beat
# interval sweeping the outbox for due rows; an explicit, named constant
# rather than a magic number in `beat_schedule` below.
GITHUB_CHECKS_SWEEP_INTERVAL_SECONDS = 60

celery_app = Celery(
    "orchestrator",
    broker=_settings.celery_broker_url or _settings.redis_url,
    backend=_settings.celery_result_backend or _settings.redis_url,
    include=[
        "orchestrator.workers.tasks.process_scan",
        "orchestrator.workers.tasks.github_checks",
    ],
)

celery_app.conf.task_queues = (
    Queue("scan"),
    Queue("webhook"),
    Queue("github_checks"),
)
celery_app.conf.task_default_queue = "scan"
celery_app.conf.task_routes = {
    "orchestrator.workers.tasks.process_scan.process_scan_task": {"queue": "scan"},
    "orchestrator.workers.tasks.github_checks.sweep_github_check_publications_task": {
        "queue": "github_checks"
    },
}
# PR4's disabled-by-default sweep (`Settings.github_checks_delivery_enabled`)
# is scheduled unconditionally here — the task itself, not Beat, is the
# zero-I/O gate: it returns before ever calling `claim_due` while disabled.
celery_app.conf.beat_schedule = {
    "sweep-github-check-publications": {
        "task": "orchestrator.workers.tasks.github_checks.sweep_github_check_publications_task",
        "schedule": GITHUB_CHECKS_SWEEP_INTERVAL_SECONDS,
    },
}


@worker_process_init.connect  # type: ignore[untyped-decorator]
def _init_worker_tracing(**_kwargs: object) -> None:
    """Module 13a D2 — fork-safety. `worker_process_init` fires in EACH
    forked worker child, AFTER the fork completes, never in the pre-fork
    parent process (unlike a module-import-time call, which would run once
    in the parent and hand every child a broken, fork-inherited exporter
    thread/gRPC channel). Deliberately NOT called at module import scope."""
    configure_tracing(f"{_settings.otel_service_name}-worker")
    instrument_celery()
    start_worker_heartbeat()


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _shutdown_worker_tracing(**_kwargs: object) -> None:
    """Module 13a follow-up — counterpart to `_init_worker_tracing`:
    `worker_process_shutdown` fires in EACH forked worker child on graceful
    shutdown (worker restart, rolling deploy), and is what flushes any spans
    buffered but not yet exported — the gap left by removing the SDK's
    `atexit`-based flush (`shutdown_on_exit=False`). `shutdown_tracing()` is
    a safe no-op when this worker process never configured tracing; when
    configured, how long its flush can block on an unreachable OTLP endpoint
    is bounded by the `OTLPSpanExporter` constructor-level `timeout` set in
    `tracing.configure_tracing` (~2s), not by any argument to
    `force_flush()` itself — see `infrastructure/observability/tracing.py`
    for why."""
    try:
        shutdown_tracing()
    finally:
        stop_worker_heartbeat()
