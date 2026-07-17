"""`create_app()` wires the RFC 7807 problem+json handlers (task 3.8).

Routers are wired in PR4 (Phase 4) — no real route raises `ProblemException`
yet, so these tests attach a throwaway route to the REAL app instance
returned by `create_app()` to prove the handlers are registered at the app
level and fire on a genuine request, not just present in source.
"""

from __future__ import annotations

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
