"""OpenTelemetry bootstrap (Module 13a, D1/D2/D3).

Every public function here is a no-op unless `Settings.otel_exporter_otlp_endpoint`
is explicitly set — presence of the endpoint is what gates tracing on (mirrors
the `cors_allowed_origins`/`github_webhook_secret` opt-in-via-presence
precedent). When unset, `configure_tracing` never calls
`trace.set_tracer_provider`, so `trace.get_tracer(...)` keeps returning the
OTel API's default non-recording proxy tracer — zero exporter, zero thread,
zero behavior change to the existing request/task pipeline.

`configure_tracing` MUST be called separately, post-fork, in each Celery
worker process (via a `worker_process_init` handler — see
`workers/celery_app.py`) rather than once at module import time in a
pre-fork parent process (D2): a `BatchSpanProcessor`'s background export
thread and the OTLP gRPC channel's socket do not survive `fork()` intact, so
initializing before the fork would silently hand every forked child a
broken exporter.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

from orchestrator.infrastructure.config.settings import get_settings

_configured = False

# Bounded per-export timeout (seconds) passed to `OTLPSpanExporter` itself —
# this is what actually bounds how long a graceful SIGTERM/rolling-deploy/
# worker-restart can block on `shutdown_tracing()`'s `force_flush()` if the
# OTLP endpoint is completely unreachable at shutdown time.
#
# NOT `force_flush(timeout_millis=...)`: as of `opentelemetry-sdk==1.44.0`,
# `BatchSpanProcessor`/`BatchProcessor.force_flush()` silently ignores its
# `timeout_millis` argument entirely (see
# `opentelemetry.sdk._shared_internal.BatchProcessor.force_flush`, which
# never reads the parameter) — an upstream bug tracked at
# https://github.com/open-telemetry/opentelemetry-python/issues/4568
# ("TODO: Fix force flush so the timeout is used"). The exporter's own
# constructor-level `timeout` (seconds, not milliseconds) is what actually
# bounds each export attempt's blocking gRPC call, so that is the layer this
# module must configure.
_OTLP_EXPORTER_TIMEOUT_SECONDS = 2


def configure_tracing(service_name: str) -> bool:
    """Initialize a `TracerProvider` + OTLP-gRPC exporter for this process.

    Returns `False` (no-op) when `otel_exporter_otlp_endpoint` is empty.
    Returns `True` without re-creating the provider/exporter on repeated
    calls (idempotency guard) once configured.
    """
    global _configured

    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return False
    if _configured:
        return True

    resource = Resource.create(
        {SERVICE_NAME: service_name, "deployment.environment": settings.environment}
    )
    # `shutdown_on_exit=False`: the SDK default (`True`) registers an
    # `atexit` handler that can block process exit up to 30s (the
    # `BatchSpanProcessor` default flush/shutdown timeout) if the OTLP
    # endpoint is unreachable at shutdown — tracing must never block a
    # graceful SIGTERM past normal container stop-grace periods.
    provider = TracerProvider(
        resource=resource, sampler=ParentBased(ALWAYS_ON), shutdown_on_exit=False
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=True,
                timeout=_OTLP_EXPORTER_TIMEOUT_SECONDS,
            )
        )
    )
    trace.set_tracer_provider(provider)
    _configured = True
    return True


def instrument_fastapi(app: FastAPI) -> None:
    """Auto-instrument the FastAPI app for server spans. No-op when disabled."""
    if get_settings().otel_exporter_otlp_endpoint:
        FastAPIInstrumentor.instrument_app(app)


def instrument_celery() -> None:
    """Auto-instrument Celery producer/consumer spans (context propagation
    across the API -> worker boundary). No-op when disabled."""
    if get_settings().otel_exporter_otlp_endpoint:
        CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]


def shutdown_tracing() -> None:
    """Flush any buffered-but-unexported spans on graceful shutdown.

    Review follow-up: disabling the SDK's `atexit`-based flush
    (`shutdown_on_exit=False` above) fixed the unreachable-endpoint blocking
    risk, but left NO compensating flush hook — every graceful shutdown
    (SIGTERM, rolling deploy, worker restart) was silently dropping whatever
    spans were buffered but not yet exported, even when the OTLP endpoint
    was perfectly reachable. This restores an explicit flush.

    The bound on how long that flush can block if the OTLP endpoint is
    unreachable comes from `OTLPSpanExporter`'s own constructor-level
    `timeout=_OTLP_EXPORTER_TIMEOUT_SECONDS` set in `configure_tracing`
    above — NOT from a `force_flush(timeout_millis=...)` argument here.
    `force_flush()` is called bare (no timeout kwarg) deliberately: as of
    `opentelemetry-sdk==1.44.0`, `BatchSpanProcessor.force_flush()` silently
    ignores its `timeout_millis` argument (upstream bug, see
    `_OTLP_EXPORTER_TIMEOUT_SECONDS`'s docstring above for the tracking
    issue), so passing one here would be dead, misleading code.

    Guarded by the same `_configured` check as the rest of this module: a
    safe no-op when tracing was never configured (the off-by-default case)
    — no attempt to flush, no exception.
    """
    if not _configured:
        return
    # `trace.get_tracer_provider()`'s return type is the OTel API's abstract
    # `TracerProvider`, which has no `force_flush` — only the SDK's concrete
    # implementation (which `configure_tracing` always installs before
    # `_configured` is set `True`) does.
    trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]
