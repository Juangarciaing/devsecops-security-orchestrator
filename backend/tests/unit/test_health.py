"""GET /health is a liveness probe: 200 + status ok, unauthenticated, dependency-agnostic."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.api.main import create_app


def test_health_returns_200_with_status_ok(valid_env: None) -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ignores_unreachable_dependencies(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:1/unreachable")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:2/0")

    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
