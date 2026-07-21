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
    provider = TracerProvider(resource=resource, sampler=ParentBased(ALWAYS_ON))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
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
