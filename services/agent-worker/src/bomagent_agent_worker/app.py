from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from bomagent_agent_worker import __version__
from bomagent_agent_worker.trace_cap import DEFAULT_TRACE_MAX_BYTES
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.logging import get_logger
from bomagent_common.messaging import (
    Handler,
    Message,
    Queue,
    consume_forever,
    consumer_queue,
    stop_consumer,
)
from bomagent_common.service import Lifespan, create_service_app
from bomagent_common.shutdown import shutdown_of
from bomagent_common.telemetry import shutdown_telemetry

log = get_logger(__name__)


class Settings(ServiceSettings):
    service_name: str = "bomagent-agent-worker"
    queue_url: str | None = None  # SQS queue with work for this worker
    queue_name: str = "runs"  # postgres queue backend: queue name in app.queue_messages
    queue_wait_seconds: int = 10
    #: on shutdown the current message may finish for this long, then it is cancelled and
    #: released (inside ECS's default 30 s stop timeout)
    consumer_stop_grace_s: float = 20.0
    files_bucket: str = "bomagent-local-files"
    llm_gateway_url: str | None = None
    llm_gateway_key: str | None = None
    embedding_model: str = "fake-embedding"
    #: a running run idle for this long is resumed from its checkpoint on redelivery; must
    #: exceed the longest single LLM call (``bomagent_llm.chat.CALL_TIMEOUT_MAX_S``)
    run_resume_stale_s: float = 1200.0
    run_max_resumes: int = 3
    #: size cap of the ``runs.trace`` column in bytes (0 = off); ``trace.json`` stays complete
    run_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES


def build_handler(settings: Settings) -> Handler:
    from bomagent_agent_worker.handler import RunWorker
    from bomagent_agents.fake_responder import heuristic_responder
    from bomagent_common.storage import make_object_store
    from bomagent_kb import KnowledgeBase
    from bomagent_llm.chat import ChatClient, FakeChat, GatewayChat
    from bomagent_llm.embeddings import EmbeddingClient, GatewayEmbeddings, HashingEmbeddings

    if settings.database_url is None:
        raise RuntimeError("BOMAGENT_DATABASE_URL is required")
    chat: ChatClient
    embedder: EmbeddingClient
    if settings.llm_gateway_url and settings.llm_gateway_key:
        chat = GatewayChat(settings.llm_gateway_url, settings.llm_gateway_key)
        embedder = GatewayEmbeddings(
            settings.llm_gateway_url, settings.llm_gateway_key, settings.embedding_model
        )
    elif settings.environment in {"local", "test"}:  # never in dev/staging/prod
        chat, embedder = FakeChat(heuristic_responder), HashingEmbeddings()
    else:
        raise RuntimeError("BOMAGENT_LLM_GATEWAY_URL/KEY are required outside local/test")
    worker = RunWorker(
        engine=make_engine(settings.database_url),
        store=make_object_store(settings, settings.files_bucket),
        chat=chat,
        kb=KnowledgeBase(embedder),
        allow_unregistered=settings.environment in {"local", "test"},
        resume_stale_after_s=settings.run_resume_stale_s,
        max_resumes=settings.run_max_resumes,
        trace_max_bytes=settings.run_trace_max_bytes,
    )
    return worker.handle


def _make_lifespan(settings: Settings, queue: Queue | None, handler: Handler) -> Lifespan:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        shutdown_of(app).on_request(stop.set)  # SIGTERM: claim nothing new
        task: asyncio.Task[None] | None = None
        if queue is not None:
            task = asyncio.create_task(
                consume_forever(
                    queue,
                    handler,
                    stop=stop,
                    wait_seconds=settings.queue_wait_seconds,
                    max_messages=1,  # slow handlers: see consume_forever
                    # an interrupted run comes back when it can be taken over (resume)
                    release_delay_s=settings.run_resume_stale_s,
                )
            )
            log.info("consumer_started", queue="runs")
        try:
            yield
        finally:
            if task is not None:
                await stop_consumer(task, stop, grace_s=settings.consumer_stop_grace_s)
            stop.set()
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
        title="BOM Agent agent worker",
        readiness=readiness,
        lifespan=_make_lifespan(
            settings, queue, handler or (build_handler(settings) if queue else _noop)
        ),
        docs=False,
    )
