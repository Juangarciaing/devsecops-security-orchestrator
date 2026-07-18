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
from kombu import Queue

from orchestrator.infrastructure.config.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "orchestrator",
    broker=_settings.celery_broker_url or _settings.redis_url,
    backend=_settings.celery_result_backend or _settings.redis_url,
    include=["orchestrator.workers.tasks.process_scan"],
)

celery_app.conf.task_queues = (
    Queue("scan"),
    Queue("webhook"),
)
celery_app.conf.task_default_queue = "scan"
celery_app.conf.task_routes = {
    "orchestrator.workers.tasks.process_scan.process_scan_task": {"queue": "scan"},
}
