"""`create_app()` wires the RFC 7807 problem+json handlers (task 3.8).

Routers are wired in PR4 (Phase 4) — no real route raises `ProblemException`
yet, so these tests attach a throwaway route to the REAL app instance
returned by `create_app()` to prove the handlers are registered at the app
level and fire on a genuine request, not just present in source.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from orchestrator.api.main import create_app
from orchestrator.api.v1.errors.problem import ProblemException


def test_create_app_wires_problem_exception_handler(valid_env: None) -> None:
    app = create_app()

    @app.get("/__test_raises_problem__")
    def _raise() -> None:
        raise ProblemException(status_code=401, title="Unauthorized", detail="no token")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test_raises_problem__")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Unauthorized"


def test_create_app_wires_validation_error_handler(valid_env: None) -> None:
    app = create_app()

    class _Payload(BaseModel):
        name: str

    @app.post("/__test_validate__")
    def _validate(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/__test_validate__", json={})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def test_create_app_wires_unhandled_exception_handler(valid_env: None) -> None:
    app = create_app()

    @app.get("/__test_boom__")
    def _boom() -> None:
        raise RuntimeError("secret internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test_boom__")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert "secret internal detail" not in response.text


def test_create_app_has_no_cors_headers_by_default(valid_env: None) -> None:
    """CORS is opt-in — an unconfigured deployment gets zero behavior change."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_create_app_allows_configured_cors_origin(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting `CORS_ALLOWED_ORIGINS` enables cross-origin requests from that origin only."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    other_origin_response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in other_origin_response.headers


def test_create_app_wires_tracing_bootstrap_at_factory_time(valid_env: None) -> None:
    """Module 13a task 2.3/2.4: `create_app()` MUST call the tracing bootstrap
    (configure the API's own provider, then instrument Celery-producer spans
    and the FastAPI app itself) so a fresh app instance always attempts
    tracing setup — each call is a no-op when tracing is disabled (D1)."""
    with (
        patch("orchestrator.api.main.configure_tracing") as mock_configure,
        patch("orchestrator.api.main.instrument_celery") as mock_instrument_celery,
        patch("orchestrator.api.main.instrument_fastapi") as mock_instrument_fastapi,
    ):
        app = create_app()

    mock_configure.assert_called_once_with("orchestrator-api")
    mock_instrument_celery.assert_called_once()
    mock_instrument_fastapi.assert_called_once_with(app)
