"""FastAPI application factory.

`create_app()` returns a fresh `FastAPI` instance per call so tests can build
isolated app instances and later modules can wire dependency injection without
relying on a module-level singleton.
"""

from __future__ import annotations

from fastapi import FastAPI

from orchestrator.api.v1.errors.problem import register_exception_handlers
from orchestrator.api.v1.routers.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="DevSecOps Security Orchestrator", version="0.1.0")
    register_exception_handlers(app)
    app.include_router(health_router)
    return app
