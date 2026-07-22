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

from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.observability import tracing


@pytest.fixture(autouse=True)
def _reset_tracing_module_state() -> None:
    """`configure_tracing` is idempotency-guarded by a module-level flag —
    reset it between tests so each test observes a fresh gate check. Every
    test below that exercises the enabled path mocks `TracerProvider`,
    `BatchSpanProcessor`, `OTLPSpanExporter`, and `trace` construction, so no
    real background export thread or process-wide OTel global is ever
    created here — there is nothing further to tear down (a real
    `BatchSpanProcessor` targeting an unreachable endpoint would otherwise
    leak a live daemon export thread for the rest of the pytest session)."""
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

    with (
        patch(
            "orchestrator.infrastructure.observability.tracing.TracerProvider"
        ) as mock_provider_cls,
        patch("orchestrator.infrastructure.observability.tracing.BatchSpanProcessor"),
        patch("orchestrator.infrastructure.observability.tracing.OTLPSpanExporter"),
        patch("orchestrator.infrastructure.observability.tracing.trace") as mock_trace,
    ):
        result = tracing.configure_tracing("orchestrator-api")

    assert result is True
    mock_trace.set_tracer_provider.assert_called_once_with(mock_provider_cls.return_value)


def test_configure_tracing_disables_shutdown_on_exit(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Review WARNING: the OTel SDK's `TracerProvider` default
    `shutdown_on_exit=True` registers an `atexit` handler that can block
    process exit up to 30s (`BatchSpanProcessor`'s default flush/shutdown
    timeout) if the OTLP endpoint is unreachable at shutdown — tracing must
    never block a graceful SIGTERM past normal container stop-grace
    periods."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()

    with (
        patch(
            "orchestrator.infrastructure.observability.tracing.TracerProvider"
        ) as mock_provider_cls,
        patch("orchestrator.infrastructure.observability.tracing.BatchSpanProcessor"),
        patch("orchestrator.infrastructure.observability.tracing.OTLPSpanExporter"),
        patch("orchestrator.infrastructure.observability.tracing.trace"),
    ):
        tracing.configure_tracing("orchestrator-api")

    _, kwargs = mock_provider_cls.call_args
    assert kwargs["shutdown_on_exit"] is False


def test_configure_tracing_only_constructs_the_provider_once_across_repeated_calls(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Guards THIS module's own `if _configured: return True` guard — not
    OTel's unrelated process-wide `set_tracer_provider` set-once semantics
    (which silently keeps the first-ever provider on a second call and
    would therefore pass even if this module's own guard were deleted).
    Asserting the construction call count is what actually proves the
    second `configure_tracing()` call short-circuits before doing any
    work."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()

    with (
        patch(
            "orchestrator.infrastructure.observability.tracing.TracerProvider"
        ) as mock_provider_cls,
        patch(
            "orchestrator.infrastructure.observability.tracing.BatchSpanProcessor"
        ) as mock_processor_cls,
        patch(
            "orchestrator.infrastructure.observability.tracing.OTLPSpanExporter"
        ) as mock_exporter_cls,
        patch("orchestrator.infrastructure.observability.tracing.trace"),
    ):
        first_result = tracing.configure_tracing("orchestrator-api")
        second_result = tracing.configure_tracing("orchestrator-api")

    assert first_result is True
    assert second_result is True
    mock_provider_cls.assert_called_once()
    mock_processor_cls.assert_called_once()
    mock_exporter_cls.assert_called_once()


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


def test_shutdown_tracing_is_a_noop_when_not_configured(valid_env: None) -> None:
    """Review follow-up: `shutdown_tracing` must be a safe no-op when tracing
    was never configured (the off-by-default case) — no attempt to flush,
    no exception."""
    get_settings.cache_clear()

    with patch("orchestrator.infrastructure.observability.tracing.trace") as mock_trace:
        tracing.shutdown_tracing()

    mock_trace.get_tracer_provider.assert_not_called()


def test_shutdown_tracing_flushes_the_active_provider_with_a_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Review follow-up: removing the SDK's `atexit`-based flush left no
    compensating hook, silently dropping buffered spans on every graceful
    shutdown even when the OTLP endpoint was reachable. `shutdown_tracing`
    must force-flush the active provider, bounded to 2000ms so it can never
    reintroduce the original blocking-shutdown risk if the endpoint is
    unreachable."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    get_settings.cache_clear()
    tracing._configured = True

    with patch("orchestrator.infrastructure.observability.tracing.trace") as mock_trace:
        tracing.shutdown_tracing()

    mock_provider = mock_trace.get_tracer_provider.return_value
    mock_provider.force_flush.assert_called_once_with(timeout_millis=2000)
