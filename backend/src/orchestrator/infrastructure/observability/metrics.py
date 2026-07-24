"""Bounded Prometheus metrics owned exclusively by the infrastructure layer."""

from __future__ import annotations

import logging

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

from orchestrator.domain.value_objects.enums import ScannerType

logger = logging.getLogger(__name__)

API_REGISTRY = CollectorRegistry()
SCAN_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1800)
SCANNER_DURATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)

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


def _status_class(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "2xx"
    if 400 <= status_code < 500:
        return "4xx"
    return "5xx"
