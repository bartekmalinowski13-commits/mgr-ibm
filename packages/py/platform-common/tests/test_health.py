"""Liveness and readiness endpoints."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from bomagent_common.health import health_router


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(path)


async def test_readyz_reports_checks_and_optional_app_info():
    async def ok() -> bool:
        return True

    app = FastAPI()
    app.include_router(health_router("svc", "1", {"database": ok}))
    app.state.readyz_info = {"llm": "gateway"}
    body = (await _get(app, "/readyz")).json()
    assert body["checks"] == {"database": True}
    assert body["llm"] == "gateway"


async def test_readyz_without_info_is_unchanged():
    app = FastAPI()
    app.include_router(health_router("svc", "1"))
    body = (await _get(app, "/readyz")).json()
    assert set(body) == {"status", "service", "checks"}
