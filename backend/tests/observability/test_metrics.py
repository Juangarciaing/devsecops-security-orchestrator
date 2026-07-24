"""Prometheus contract tests for the API-owned metrics registry."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from orchestrator.api.main import create_app
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.observability.metrics import (
    API_REGISTRY,
    SCAN_DURATION_BUCKETS,
    record_api_request,
    record_scan_accepted,
)


def _exposition() -> str:
    return generate_latest(API_REGISTRY).decode("utf-8")


def test_api_metric_contract_uses_only_bounded_labels_and_scan_buckets() -> None:
    record_api_request("GET", "/repositories/{repository_id}/scans", 202)
    record_scan_accepted(ScannerType.SECRETS)

    exposition = _exposition()

    assert (
        'orchestrator_api_requests_total{method="GET",'
        'route="/repositories/{repository_id}/scans",status_class="2xx"}' in exposition
    )
    assert 'orchestrator_scan_accepted_total{queue="scan",scanner_type="secrets"}' in exposition
    assert SCAN_DURATION_BUCKETS == (1, 5, 15, 30, 60, 120, 300, 600, 1800)


def test_metric_exposition_never_contains_unsafe_scan_values() -> None:
    unsafe_url = "https://github.example/acme/private-repository.git"
    unsafe_sha = "0123456789abcdef0123456789abcdef01234567"
    unsafe_exception = "credential leaked: super-secret"

    record_scan_accepted(ScannerType.SECRETS)
    exposition = _exposition()

    assert unsafe_url not in exposition
    assert unsafe_sha not in exposition
    assert unsafe_exception not in exposition


def test_recreated_apps_expose_the_same_custom_registry_without_duplicates(valid_env: None) -> None:
    first = create_app()
    second = create_app()

    first_response = TestClient(first).get("/metrics")
    second_response = TestClient(second).get("/metrics")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.headers["content-type"].startswith("text/plain")
    assert "orchestrator_api_requests_total" in first_response.text


def test_request_accounting_uses_template_routes_and_excludes_metrics(valid_env: None) -> None:
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    metrics_response = client.get("/metrics")

    assert (
        'orchestrator_api_requests_total{method="GET",route="/health",status_class="2xx"}'
        in metrics_response.text
    )
    assert 'route="/metrics"' not in metrics_response.text


def test_accepted_metric_is_recorded_only_after_delay_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orchestrator.api.v1.routers import scans

    recorded: list[ScannerType] = []
    delayed: list[str] = []
    task = SimpleNamespace(delay=lambda task_id: delayed.append(task_id))
    monkeypatch.setitem(
        sys.modules,
        "orchestrator.workers.tasks.process_scan",
        SimpleNamespace(process_scan_task=task),
    )
    monkeypatch.setattr(scans, "record_scan_accepted", recorded.append, raising=False)

    scans.enqueue_committed_scan("task-123", ScannerType.SECRETS)

    assert delayed == ["task-123"]
    assert recorded == [ScannerType.SECRETS]


def test_accepted_metric_is_not_recorded_when_delay_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.api.v1.routers import scans

    recorded: list[ScannerType] = []

    def _fail_delay(_task_id: str) -> None:
        raise RuntimeError("broker unavailable")

    task = SimpleNamespace(delay=_fail_delay)
    monkeypatch.setitem(
        sys.modules,
        "orchestrator.workers.tasks.process_scan",
        SimpleNamespace(process_scan_task=task),
    )
    monkeypatch.setattr(scans, "record_scan_accepted", recorded.append, raising=False)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        scans.enqueue_committed_scan("task-456", ScannerType.SECRETS)

    assert recorded == []
