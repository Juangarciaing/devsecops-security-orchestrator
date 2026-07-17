"""RFC 7807 `application/problem+json` error envelope.

`ProblemDetail` is the response shape; `ProblemException` is what application
code (DI guards, use cases) raises to produce a specific problem response;
`register_exception_handlers` wires the FastAPI handlers for `ProblemException`,
FastAPI's own `RequestValidationError` (422), and any otherwise-unhandled
`Exception` (500, no internal detail leaked).
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

_PROBLEM_JSON = "application/problem+json"


class ProblemDetail(BaseModel):
    """RFC 7807 problem detail body."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class ProblemException(Exception):
    """Raised by application code to produce a specific RFC 7807 response."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type_ = type_
        super().__init__(detail or title)


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=_PROBLEM_JSON,
    )


async def _handle_problem_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemException)  # noqa: S101 — enforced by add_exception_handler
    return _problem_response(
        ProblemDetail(
            type=exc.type_,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
        )
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    """Convert framework-level `HTTPException` (e.g. `HTTPBearer` auto-error on a
    missing/malformed Authorization header) into the same RFC 7807 shape used
    by application-raised `ProblemException`."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 — enforced by add_exception_handler
    return _problem_response(
        ProblemDetail(
            title=HTTPStatus(exc.status_code).phrase,
            status=exc.status_code,
            detail=str(exc.detail),
        )
    )


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 — enforced by add_exception_handler
    return _problem_response(
        ProblemDetail(
            title=HTTPStatus(status.HTTP_422_UNPROCESSABLE_CONTENT).phrase,
            status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc.errors()),
        )
    )


async def _handle_unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    return _problem_response(
        ProblemDetail(
            title=HTTPStatus(status.HTTP_500_INTERNAL_SERVER_ERROR).phrase,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the RFC 7807 problem+json handlers on `app`."""
    app.add_exception_handler(ProblemException, _handle_problem_exception)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unhandled_exception)
