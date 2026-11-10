from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Handler, Message, SqsQueue, consume_forever
from bomagent_common.service import Lifespan, create_service_app
from bomagent_common.telemetry import shutdown_telemetry
from bomagent_ingest import __version__

log = get_logger(__name__)


class Settings(ServiceSettings):
    service_name: str = "bomagent-ingest-worker"
    queue_url: str | None = None  # SQS queue with work for this worker
    queue_wait_seconds: int = 10
    files_bucket: str = "bomagent-local-files"


def build_handler(settings: Settings) -> Handler:
    from bomagent_common.storage import S3ObjectStore
    from bomagent_ingest.handler import DesignIngestor

    if settings.database_url is None:
        raise RuntimeError("BOMAGENT_DATABASE_URL is required")
    ingestor = DesignIngestor(
        engine=make_engine(settings.database_url),
        store=S3ObjectStore(
            settings.files_bucket,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ),
    )
    return ingestor.handle


def _make_lifespan(settings: Settings, handler: Handler) -> Lifespan:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        task: asyncio.Task[None] | None = None
        if settings.queue_url:
            queue = SqsQueue(
                settings.queue_url,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            task = asyncio.create_task(
                consume_forever(queue, handler, stop=stop, wait_seconds=settings.queue_wait_seconds)
            )
            log.info("consumer_started", queue="ingest")
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task
            shutdown_telemetry()

    return lifespan


async def handle(message: Message) -> None:
    """Placeholder dispatch; real handlers are registered in later milestones."""
    log.info("message_received", message_type=message.type)


def create_app(settings: Settings | None = None, handler: Handler | None = None) -> FastAPI:
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
        title="BOM Agent ingest worker",
        readiness=readiness,
        lifespan=_make_lifespan(
            settings, handler or (build_handler(settings) if settings.queue_url else handle)
        ),
        docs=False,
    )
