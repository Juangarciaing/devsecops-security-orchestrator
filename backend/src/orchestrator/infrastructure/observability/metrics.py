"""Bounded Prometheus metrics owned exclusively by the infrastructure layer."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

from orchestrator.domain.value_objects.enums import ScannerType

logger = logging.getLogger(__name__)

API_REGISTRY = CollectorRegistry()
SCAN_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1800)
SCANNER_DURATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
STALE_WORKER_SECONDS = 60
FailureCategory = Literal[
    "checkout", "scanner", "timeout", "container_runtime", "persistence", "unknown"
]
_FAILURE_CATEGORIES: frozenset[str] = frozenset(
    {"checkout", "scanner", "timeout", "container_runtime", "persistence", "unknown", "none"}
)

_api_requests = Counter(
    "orchestrator_api_requests",
    "Completed API requests.",
    ("method", "route", "status_class"),
    registry=API_REGISTRY,
)
_scan_accepted = Counter(
    "orchestrator_scan_accepted",
    "Accepted scan tasks.",
    ("queue", "scanner_type"),
    registry=API_REGISTRY,
)
_scan_started = Counter(
    "orchestrator_scan_started",
    "Started scans.",
    ("queue", "scanner_type"),
    registry=API_REGISTRY,
)
_scan_retries = Counter(
    "orchestrator_scan_retries",
    "Non-terminal scan retries.",
    ("queue", "scanner_type", "failure_category"),
    registry=API_REGISTRY,
)
_scan_terminal = Counter(
    "orchestrator_scan_terminal",
    "Terminal scan outcomes.",
    ("scanner_type", "outcome", "failure_category"),
    registry=API_REGISTRY,
)
_scan_duration = Histogram(
    "orchestrator_scan_duration_seconds",
    "Logical scan duration.",
    ("scanner_type", "outcome"),
    buckets=SCAN_DURATION_BUCKETS,
    registry=API_REGISTRY,
)
_scanner_duration = Histogram(
    "orchestrator_scanner_duration_seconds",
    "Scanner execution duration.",
    ("scanner_type", "outcome"),
    buckets=SCANNER_DURATION_BUCKETS,
    registry=API_REGISTRY,
)
_container_duration = Histogram(
    "orchestrator_container_duration_seconds",
    "Container execution duration.",
    ("outcome",),
    buckets=SCANNER_DURATION_BUCKETS,
    registry=API_REGISTRY,
)
_scan_findings = Counter(
    "orchestrator_scan_findings",
    "Committed scan findings.",
    ("scanner_type",),
    registry=API_REGISTRY,
)

_worker_scan_started = Counter(
    "orchestrator_scan_started", "Started scans.", ("queue", "scanner_type"), registry=None
)
_worker_scan_retries = Counter(
    "orchestrator_scan_retries",
    "Non-terminal scan retries.",
    ("queue", "scanner_type", "failure_category"),
    registry=None,
)
_worker_scan_terminal = Counter(
    "orchestrator_scan_terminal",
    "Terminal scan outcomes.",
    ("scanner_type", "outcome", "failure_category"),
    registry=None,
)
_worker_scan_duration = Histogram(
    "orchestrator_scan_duration_seconds",
    "Logical scan duration.",
    ("scanner_type", "outcome"),
    buckets=SCAN_DURATION_BUCKETS,
    registry=None,
)
_worker_scanner_duration = Histogram(
    "orchestrator_scanner_duration_seconds",
    "Scanner execution duration.",
    ("scanner_type", "outcome"),
    buckets=SCANNER_DURATION_BUCKETS,
    registry=None,
)
_worker_container_duration = Histogram(
    "orchestrator_container_duration_seconds",
    "Container execution duration.",
    ("outcome",),
    buckets=SCANNER_DURATION_BUCKETS,
    registry=None,
)
_worker_scan_findings = Counter(
    "orchestrator_scan_findings", "Committed scan findings.", ("scanner_type",), registry=None
)
_worker_processes = Gauge(
    "orchestrator_worker_processes",
    "Live worker processes.",
    multiprocess_mode="livesum",
    registry=None,
)


def record_api_request(method: str, route: str, status_code: int) -> None:
    """Record a completed request using its router template, never request data."""
    try:
        _api_requests.labels(
            method=method,
            route=route,
            status_class=_status_class(status_code),
        ).inc()
    except Exception:
        logger.exception("unable to record API request metric")


def record_scan_accepted(scanner_type: ScannerType) -> None:
    """Record an accepted task only after its database commit and broker enqueue."""
    try:
        _scan_accepted.labels(queue="scan", scanner_type=scanner_type.value).inc()
    except Exception:
        logger.exception("unable to record accepted scan metric")


def render_api_metrics() -> tuple[bytes, str]:
    """Render only the API registry; no default registry is ever exposed."""
    return generate_latest(API_REGISTRY), CONTENT_TYPE_LATEST


def record_scan_started(scanner_type: ScannerType) -> None:
    _record(
        lambda: _worker_scan_started.labels(queue="scan", scanner_type=scanner_type.value).inc()
    )


def record_scan_retried(scanner_type: ScannerType, category: str) -> None:
    _record(
        lambda: _worker_scan_retries.labels(
            queue="scan",
            scanner_type=scanner_type.value,
            failure_category=_failure_category(category),
        ).inc()
    )


def record_scan_terminal(
    scanner_type: ScannerType,
    outcome: Literal["completed", "failed"],
    category: str,
    duration: float,
) -> None:
    try:
        _worker_scan_terminal.labels(
            scanner_type=scanner_type.value,
            outcome=outcome,
            failure_category=_failure_category(category),
        ).inc()
        _worker_scan_duration.labels(scanner_type=scanner_type.value, outcome=outcome).observe(
            duration
        )
    except Exception:
        logger.exception("unable to record worker metric")


def record_scanner_duration(scanner_type: ScannerType, outcome: str, duration: float) -> None:
    try:
        _worker_scanner_duration.labels(scanner_type=scanner_type.value, outcome=outcome).observe(
            duration
        )
    except Exception:
        logger.exception("unable to record worker metric")


def record_container_duration(outcome: str, duration: float) -> None:
    _record(lambda: _worker_container_duration.labels(outcome=outcome).observe(duration))


def record_scan_findings(scanner_type: ScannerType, count: int) -> None:
    _record(lambda: _worker_scan_findings.labels(scanner_type=scanner_type.value).inc(count))


def start_worker_heartbeat() -> None:
    _record(lambda: _worker_processes.set(1))


def stop_worker_heartbeat() -> None:
    try:
        multiprocess.mark_process_dead(os.getpid())  # type: ignore[no-untyped-call]
    except Exception:
        logger.exception("unable to remove worker metric files")


def cleanup_stale_worker_files(directory: Path, *, now: datetime) -> set[int]:
    removed: set[int] = set()
    for path in directory.glob("gauge_livesum_*.db"):
        try:
            pid = int(path.stem.rsplit("_", 1)[1])
            stale = now.timestamp() - path.stat().st_mtime > STALE_WORKER_SECONDS
            if pid != os.getpid() and (stale or not _pid_is_alive(pid)):
                for sibling in directory.glob(f"*_{pid}.db"):
                    sibling.unlink(missing_ok=True)
                removed.add(pid)
        except (OSError, ValueError):
            logger.exception("unable to clean stale worker metric file")
    return removed


def build_worker_scrape_registry() -> CollectorRegistry:
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not directory:
        raise RuntimeError("PROMETHEUS_MULTIPROC_DIR is required for worker metrics")
    cleanup_stale_worker_files(Path(directory), now=datetime.now(UTC))
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    return registry


def render_worker_metrics(registry: bool = False) -> str | CollectorRegistry:
    if registry:
        return build_worker_scrape_registry()
    return generate_latest(API_REGISTRY).decode("utf-8")


def _failure_category(value: str) -> FailureCategory:
    return value if value in _FAILURE_CATEGORIES else "unknown"  # type: ignore[return-value]


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _record(callback: object) -> None:
    try:
        callback()  # type: ignore[operator]
    except Exception:
        logger.exception("unable to record worker metric")


def _status_class(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "2xx"
    if 400 <= status_code < 500:
        return "4xx"
    return "5xx"
