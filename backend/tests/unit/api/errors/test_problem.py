"""RFC 7807 `application/problem+json` error envelope.

Built against a throwaway FastAPI app (not the real `create_app()`) so the
handler wiring itself is unit-tested in isolation; `test_main.py` proves the
real `create_app()` registers these same handlers (task 3.8).
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from orchestrator.api.v1.errors.problem import ProblemException, register_exception_handlers


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    class _Payload(BaseModel):
        name: str

    @app.get("/raises-401")
    def _raises_401() -> None:
        raise ProblemException(status_code=401, title="Unauthorized", detail="Invalid token")

    @app.get("/raises-403")
    def _raises_403() -> None:
        raise ProblemException(status_code=403, title="Forbidden", detail="Insufficient role")

    @app.post("/validate")
    def _validate(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("some internal secret detail")

    @app.get("/raises-framework-401")
    def _raises_framework_401() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return app


def test_problem_exception_401_returns_problem_json_shape() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/raises-401")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 401
    assert body["title"] == "Unauthorized"
    assert body["detail"] == "Invalid token"


def test_problem_exception_403_returns_problem_json_shape() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/raises-403")

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 403
    assert body["title"] == "Forbidden"
    assert body["detail"] == "Insufficient role"


def test_request_validation_error_returns_422_problem_json() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.post("/validate", json={})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 422
    assert body["title"] == HTTPStatus.UNPROCESSABLE_CONTENT.phrase
    assert "detail" in body


def test_framework_http_exception_returns_problem_json_shape() -> None:
    """A framework-raised `HTTPException` (e.g. `HTTPBearer` auto-error on a
    missing Authorization header) MUST also be converted to problem+json,
    not FastAPI's default `{"detail": ...}` JSON body."""
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/raises-framework-401")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 401
    assert body["detail"] == "Not authenticated"


def test_unhandled_exception_returns_500_problem_json_without_leaking_internals() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert "some internal secret detail" not in response.text
