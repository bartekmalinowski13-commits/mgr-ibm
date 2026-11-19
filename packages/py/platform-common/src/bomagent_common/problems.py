"""RFC 9457 problem details (``application/problem+json``) for all HTTP errors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from bomagent_common.logging import get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_BASE = "https://bomagent.eu/problems/"
log = get_logger(__name__)


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[dict[str, Any]] | None = None


class ProblemError(Exception):
    """Raise from handlers to return a typed problem response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        slug: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.headers = headers or {}
        self.problem = Problem(
            type=f"{PROBLEM_BASE}{slug}" if slug else "about:blank",
            title=title,
            status=status,
            detail=detail,
        )


def _response(
    problem: Problem, request: Request, headers: dict[str, str] | None = None
) -> JSONResponse:
    problem.instance = problem.instance or request.url.path
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def problem_response(problem: Problem, request: Request) -> JSONResponse:
    """Problem response outside exception handlers (e.g. in middleware)."""
    return _response(problem, request)


def install_problem_handlers(
    app: FastAPI, *, error_headers: Mapping[str, str] | None = None
) -> None:
    """Problem+json for every error. ``error_headers`` are added to the response of an
    unexpected exception: Starlette answers those in ``ServerErrorMiddleware``, outside any
    user middleware, so headers set by middleware (e.g. security headers) never reach it."""

    async def _problem(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ProblemError)
        return _response(exc.problem.model_copy(), request, exc.headers or None)

    async def _http(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        return _response(
            Problem(title=_title(exc.status_code), status=exc.status_code, detail=str(exc.detail)),
            request,
        )

    async def _validation(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return _response(
            Problem(
                type=f"{PROBLEM_BASE}validation-error",
                title="Request validation failed",
                status=422,
                errors=errors,
            ),
            request,
        )

    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        # the details stay in the log; the client sees a generic problem (no stack trace)
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            request_id=request.headers.get("x-request-id"),
            error=type(exc).__name__,
            exc_info=exc,
        )
        return _response(
            Problem(
                type=f"{PROBLEM_BASE}internal",
                title="Internal Server Error",
                status=500,
                detail="an unexpected error occurred; it has been logged",
            ),
            request,
            dict(error_headers or {}),
        )

    app.add_exception_handler(Exception, _internal)
    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validation)


def _title(status: int) -> str:
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"
