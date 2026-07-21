"""`infrastructure.observability.tracing` — off-by-default OTel bootstrap
(Module 13a, tasks 1.4-1.7, 2.1-2.2).

`configure_tracing`/`instrument_fastapi`/`instrument_celery` MUST be pure
no-ops when `Settings.otel_exporter_otlp_endpoint` is empty (the default) —
zero exporter, zero provider mutation, zero behavior change to the existing
request/task pipeline (spec: "Tracing Is Opt-In and Off by Default").
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider

from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.observability import tracing


@pytest.fixture(autouse=True)
def _reset_tracing_module_state() -> None:
    """`configure_tracing` is idempotency-guarded by a module-level flag —
    reset it between tests so each test observes a fresh gate check."""
    tracing._configured = False


def test_configure_tracing_is_a_noop_when_endpoint_unset(valid_env: None) -> None:
    get_settings.cache_clear()

    with patch("orchestrator.infrastructure.observability.tracing.trace") as mock_trace:
        result = tracing.configure_tracing("orchestrator-api")

    assert result is False
    mock_trace.set_tracer_provider.assert_not_called()


def test_configure_tracing_sets_a_tracer_provider_when_endpoint_set(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()

    result = tracing.configure_tracing("orchestrator-api")

    assert result is True
    from opentelemetry import trace as otel_trace

    assert isinstance(otel_trace.get_tracer_provider(), TracerProvider)


def test_configure_tracing_is_idempotent_across_repeated_calls(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()

    first_result = tracing.configure_tracing("orchestrator-api")
    from opentelemetry import trace as otel_trace

    provider_after_first_call = otel_trace.get_tracer_provider()

    second_result = tracing.configure_tracing("orchestrator-api")

    assert first_result is True
    assert second_result is True
    assert otel_trace.get_tracer_provider() is provider_after_first_call


def test_instrument_fastapi_is_a_noop_when_endpoint_unset(valid_env: None) -> None:
    get_settings.cache_clear()
    app = MagicMock()

    with patch(
        "orchestrator.infrastructure.observability.tracing.FastAPIInstrumentor"
    ) as mock_instrumentor:
        tracing.instrument_fastapi(app)

    mock_instrumentor.instrument_app.assert_not_called()


def test_instrument_celery_is_a_noop_when_endpoint_unset(valid_env: None) -> None:
    get_settings.cache_clear()

    with patch(
        "orchestrator.infrastructure.observability.tracing.CeleryInstrumentor"
    ) as mock_instrumentor:
        tracing.instrument_celery()

    mock_instrumentor.assert_not_called()


def test_instrument_fastapi_instruments_the_app_when_endpoint_set(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()
    app = MagicMock()

    with patch(
        "orchestrator.infrastructure.observability.tracing.FastAPIInstrumentor"
    ) as mock_instrumentor:
        tracing.instrument_fastapi(app)

    mock_instrumentor.instrument_app.assert_called_once_with(app)


def test_instrument_celery_instruments_when_endpoint_set(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()

    with patch(
        "orchestrator.infrastructure.observability.tracing.CeleryInstrumentor"
    ) as mock_instrumentor:
        tracing.instrument_celery()

    mock_instrumentor.return_value.instrument.assert_called_once()
