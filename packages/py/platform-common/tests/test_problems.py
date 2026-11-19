from __future__ import annotations

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from bomagent_common.problems import ProblemError, install_problem_handlers


class Body(BaseModel):
    n: int


def _app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/conflict")
    async def conflict() -> None:
        raise ProblemError(409, "Conflict", "already exists", slug="duplicate")

    @app.post("/body")
    async def body(b: Body) -> Body:
        return b

    return app


async def test_problem_error_is_rfc9457():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/conflict")
    assert resp.status_code == 409
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json() == {
        "type": "https://bomagent.eu/problems/duplicate",
        "title": "Conflict",
        "status": 409,
        "detail": "already exists",
        "instance": "/conflict",
    }


async def test_validation_error_lists_fields():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.post("/body", json={"n": "x"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["type"].endswith("validation-error")
    assert data["errors"][0]["loc"] == ["body", "n"]


async def test_unexpected_error_log_falls_back_to_the_trace_id():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from structlog.testing import capture_logs

    app = FastAPI()
    install_problem_handlers(app)
    tracer = TracerProvider().get_tracer("test")
    seen: list[str] = []

    @app.get("/boom")
    async def boom() -> None:
        seen.append(format(trace.get_current_span().get_span_context().trace_id, "032x"))
        raise RuntimeError("boom")

    inner = app.build_middleware_stack

    def traced_stack():  # stands in for the OTel ASGI middleware (outermost, like FastAPI's)
        stack = inner()

        async def asgi(scope, receive, send):
            with tracer.start_as_current_span("request"):
                await stack(scope, receive, send)

        return asgi

    app.build_middleware_stack = traced_stack  # type: ignore[method-assign]
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        with capture_logs() as logs:
            resp = await c.get("/boom")
            tagged = await c.get("/boom", headers={"x-request-id": "req-1"})
    assert resp.status_code == tagged.status_code == 500
    ids = [x["request_id"] for x in logs if x["event"] == "unhandled_exception"]
    assert ids == [seen[0], "req-1"]
