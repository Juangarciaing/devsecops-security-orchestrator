"""FastAPI application factory.

`create_app()` returns a fresh `FastAPI` instance per call so tests can build
isolated app instances and later modules can wire dependency injection without
relying on a module-level singleton.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.api.v1.errors.problem import register_exception_handlers
from orchestrator.api.v1.routers.auth import router as auth_router
from orchestrator.api.v1.routers.findings import router as findings_router
from orchestrator.api.v1.routers.health import router as health_router
from orchestrator.api.v1.routers.repositories import router as repositories_router
from orchestrator.api.v1.routers.scans import router as scans_router
from orchestrator.api.v1.routers.users import router as users_router
from orchestrator.infrastructure.config.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="DevSecOps Security Orchestrator", version="0.1.0")
    register_exception_handlers(app)

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
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(repositories_router)
    app.include_router(scans_router)
    app.include_router(findings_router)
    return app
