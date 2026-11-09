from __future__ import annotations

from fastapi import FastAPI

from bomagent_api import __version__
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.service import create_service_app


class Settings(ServiceSettings):
    service_name: str = "bomagent-api"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    readiness: dict[str, ReadinessCheck] = {}
    if settings.database_url:
        engine = make_engine(settings.database_url, pool_size=2)

        async def database() -> bool:
            return await ping(engine)

        readiness["database"] = database
    return create_service_app(
        settings,
        version=__version__,
        title="BOM Agent API",
        readiness=readiness,
        docs=True,
    )
