"""Liveness (``/healthz``) and readiness (``/readyz``) endpoints shared by all services."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse

ReadinessCheck = Callable[[], Awaitable[bool]]


def health_router(
    service_name: str, version: str, checks: Mapping[str, ReadinessCheck] | None = None
) -> APIRouter:
    router = APIRouter(tags=["health"])
    checks = dict(checks or {})

    @router.get("/healthz", summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service_name, "version": version}

    @router.get("/readyz", summary="Readiness probe", response_model=None)
    async def readyz() -> JSONResponse:
        names = list(checks)
        results = await asyncio.gather(*(checks[n]() for n in names), return_exceptions=True)
        status = {n: (r is True) for n, r in zip(names, results, strict=True)}
        ok = all(status.values())
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", "service": service_name, "checks": status},
            status_code=200 if ok else 503,
        )

    return router
