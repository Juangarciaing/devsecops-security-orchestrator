"""FastAPI application factory.

`create_app()` returns a fresh `FastAPI` instance per call so tests can build
isolated app instances and later modules can wire dependency injection without
relying on a module-level singleton.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.api.v1.errors.problem import register_exception_handlers
from orchestrator.api.v1.routers.auth import router as auth_router
from orchestrator.api.v1.routers.findings import router as findings_router
from orchestrator.api.v1.routers.health import router as health_router
from orchestrator.api.v1.routers.repositories import router as repositories_router
from orchestrator.api.v1.routers.scans import router as scans_router
from orchestrator.api.v1.routers.users import router as users_router
from orchestrator.api.v1.routers.webhooks import router as webhooks_router
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.observability.tracing import (
    configure_tracing,
    instrument_celery,
    instrument_fastapi,
    shutdown_tracing,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Module 13a follow-up: FastAPI's shutdown phase is the only hook that
    fires on every graceful stop (SIGTERM, rolling deploy) — `shutdown_tracing`
    flushes buffered-but-unexported spans there and is itself a bounded
    (~2s), safe no-op when tracing was never configured."""
    yield
    shutdown_tracing()


def create_app() -> FastAPI:
    app = FastAPI(title="DevSecOps Security Orchestrator", version="0.1.0", lifespan=_lifespan)
    register_exception_handlers(app)

    # Module 13a — off by default (D1); each call below is a no-op unless
    # `OTEL_EXPORTER_OTLP_ENDPOINT` is set. `configure_tracing` sets up this
    # process's own TracerProvider/exporter; `instrument_celery` wires
    # producer-side trace-context propagation into enqueued tasks;
    # `instrument_fastapi` adds server spans for inbound requests.
    configure_tracing(f"{get_settings().otel_service_name}-api")
    instrument_celery()
    instrument_fastapi(app)

    # Opt-in only (D: settings.cors_allowed_origins) — an unconfigured
    # deployment adds no middleware and gets no CORS headers at all.
    origins = [
        origin.strip()
        for origin in get_settings().cors_allowed_origins.split(",")
        if origin.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            # Bearer-token auth only — the frontend never sends cookies or
            # sets `withCredentials`, so this stays False to avoid widening
            # the CORS contract with no corresponding client need.
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(repositories_router)
    app.include_router(scans_router)
    app.include_router(findings_router)
    app.include_router(webhooks_router)
    return app
