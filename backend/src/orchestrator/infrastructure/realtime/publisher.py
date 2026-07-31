"""Sync, fork-safe, best-effort scan-status publisher (design D-Publish-Points).

Called from `process_scan_task`'s sync body (PR2) — never from inside the
async DB helpers. `publish_scan_status` NEVER raises and NEVER retries: a
Redis outage is a log line, not a scan failure. The blanket `except
Exception` is deliberate, not a smell — see design D-Publish-Points.

The client is built lazily, on first publish, inside the forked Celery
child — never at module import in the pre-fork parent (same fork-safety
reasoning as `celery_app.py`'s tracing wiring). Celery's own broker
connection is never reused for this.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import redis

from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.realtime.channels import scan_events_channel
from orchestrator.infrastructure.realtime.events import ScanStatusEvent

logger = logging.getLogger(__name__)


def _build_client(settings: Settings) -> redis.Redis:
    """Construct a short-timeout sync Redis client. Lazy: only called on first publish."""
    return redis.Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)


def publish_scan_status(
    scan_run_id: uuid.UUID, status: ScanRunStatus, *, settings: Settings
) -> None:
    """Best-effort publish of a scan status transition. Never raises."""
    if not settings.realtime_enabled:
        return
    event = ScanStatusEvent(
        scan_run_id=scan_run_id, status=status, at=datetime.now(UTC).isoformat()
    )
    try:
        client = _build_client(settings)
        client.publish(scan_events_channel(scan_run_id), event.to_json())
    except Exception:  # noqa: BLE001 — deliberate blanket catch, see module docstring
        logger.warning("realtime publish failed for scan_run %s (best-effort)", scan_run_id)
