"""Factory for FastAPI apps of every service: logging, OTel, health, problem+json."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from bomagent_common.config import ServiceSettings
from bomagent_common.health import ReadinessCheck, health_router
from bomagent_common.logging import configure_logging
from bomagent_common.problems import install_problem_handlers
from bomagent_common.telemetry import configure_telemetry, instrument_fastapi, instrument_httpx

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_service_app(
    settings: ServiceSettings,
    *,
    version: str,
    title: str | None = None,
    readiness: Mapping[str, ReadinessCheck] | None = None,
    lifespan: Lifespan | None = None,
    docs: bool = False,
) -> FastAPI:
    configure_logging(settings.service_name, level=settings.log_level, json=settings.log_json)
    configure_telemetry(settings)
    instrument_httpx()
    app = FastAPI(
        title=title or settings.service_name,
        version=version,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    install_problem_handlers(app)
    app.include_router(health_router(settings.service_name, version, readiness))
    instrument_fastapi(app)
    return app
