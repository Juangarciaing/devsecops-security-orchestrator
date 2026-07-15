"""GET /health/ready reports Postgres/Redis reachability (503 when either is down).

The reachable-dependency branch is exercised by monkeypatching the reachability
check function directly, because this sandboxed dev environment has no live
Postgres/Redis (docker-compose wiring lands in PR2). The unreachable-dependency
branch below hits real, unmocked TCP connection attempts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.api.main import create_app
from orchestrator.infrastructure.config.settings import get_settings


def test_health_ready_returns_503_when_dependencies_unreachable(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    # Port 1 is privileged; nothing an unprivileged test process could have bound there,
    # so this connection attempt reliably and quickly fails with ECONNREFUSED.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:1/orchestrator")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:2/0")
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "down"
    assert body["redis"] == "down"


def test_health_ready_returns_200_when_dependencies_reachable(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    from orchestrator.api.v1.routers import health as health_module

    monkeypatch.setattr(health_module, "_tcp_reachable", lambda url, timeout=1.0: True)
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up", "redis": "up"}
