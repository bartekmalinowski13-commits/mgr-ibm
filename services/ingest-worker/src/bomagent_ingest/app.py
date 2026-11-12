from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Handler, Message, Queue, consume_forever, consumer_queue
from bomagent_common.service import Lifespan, create_service_app
from bomagent_common.telemetry import shutdown_telemetry
from bomagent_ingest import __version__

log = get_logger(__name__)


class Settings(ServiceSettings):
    service_name: str = "bomagent-ingest-worker"
    queue_url: str | None = None  # SQS queue with work for this worker
    queue_name: str = "ingest"  # postgres queue backend: queue name in app.queue_messages
    queue_wait_seconds: int = 10
    files_bucket: str = "bomagent-local-files"


def build_handler(settings: Settings) -> Handler:
    from bomagent_common.storage import S3ObjectStore
    from bomagent_ingest.handler import IngestWorker

    if settings.database_url is None:
        raise RuntimeError("BOMAGENT_DATABASE_URL is required")
    store = S3ObjectStore(
        settings.files_bucket, region=settings.aws_region, endpoint_url=settings.aws_endpoint_url
    )
    return IngestWorker(make_engine(settings.database_url), store).handle


def _make_lifespan(settings: Settings, queue: Queue | None, handler: Handler) -> Lifespan:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        task: asyncio.Task[None] | None = None
        if queue is not None:
            task = asyncio.create_task(
                consume_forever(
                    queue,
                    handler,
                    stop=stop,
                    wait_seconds=settings.queue_wait_seconds,
                    max_messages=1,  # slow handlers: see consume_forever
                )
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


async def _noop(message: Message) -> None:  # health-only mode (no queue configured)
    log.info("message_ignored", message_type=message.type)


def create_app(settings: Settings | None = None, handler: Handler | None = None) -> FastAPI:
    settings = settings or Settings()
    readiness: dict[str, ReadinessCheck] = {}
    if settings.database_url:
        engine = make_engine(settings.database_url, pool_size=2)

        async def database() -> bool:
            return await ping(engine)

        readiness["database"] = database
    queue = consumer_queue(settings, settings.queue_name, sqs_url=settings.queue_url)
    return create_service_app(
        settings,
        version=__version__,
        title="BOM Agent ingest worker",
        readiness=readiness,
        lifespan=_make_lifespan(
            settings, queue, handler or (build_handler(settings) if queue else _noop)
        ),
        docs=False,
    )
