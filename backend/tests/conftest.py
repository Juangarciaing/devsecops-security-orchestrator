"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure get_settings() does not leak a cached Settings instance across tests."""
    from orchestrator.infrastructure.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate every required Settings env var with a valid placeholder value."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://orchestrator:changeme@localhost:5432/orchestrator"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key")


@pytest.fixture
def span_exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """A fresh `InMemorySpanExporter` wired as the tracer provider every
    `trace.get_tracer(...)` call resolves to for the duration of one test
    (Module 13a manual-span shape tests, tasks 3.1-4.10).

    Patches `opentelemetry.trace.get_tracer_provider` directly rather than
    calling the real `trace.set_tracer_provider` — the OTel API's global
    provider can only genuinely be set ONCE per process (a `Once`-guarded
    no-op on every call after the first), which would make every test after
    the first one in the suite silently keep whichever provider won that
    race. `trace.get_tracer(...)` resolves the provider fresh, by bare name,
    at call time — the exact call site every manually-instrumented span in
    this codebase uses — so patching the module-level function is both
    correct and fully test-isolated (monkeypatch reverts it automatically).
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    return exporter
