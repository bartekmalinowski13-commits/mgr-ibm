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
