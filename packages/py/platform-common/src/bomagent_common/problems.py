"""RFC 9457 problem details (``application/problem+json``) for all HTTP errors."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_BASE = "https://bomagent.eu/problems/"


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


def install_problem_handlers(app: FastAPI) -> None:
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

    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validation)


def _title(status: int) -> str:
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"
