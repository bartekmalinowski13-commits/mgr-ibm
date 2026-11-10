from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from bomagent_agent_worker import __version__
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Handler, Message, SqsQueue, consume_forever
from bomagent_common.service import Lifespan, create_service_app
from bomagent_common.telemetry import shutdown_telemetry

log = get_logger(__name__)


class Settings(ServiceSettings):
    service_name: str = "bomagent-agent-worker"
    queue_url: str | None = None  # SQS queue with work for this worker
    queue_wait_seconds: int = 10
    files_bucket: str = "bomagent-local-files"
    llm_gateway_url: str | None = None
    llm_gateway_key: str | None = None
    embedding_model: str = "fake-embedding"
    # local/CI only: allow models with residency "local" (fake provider, Ollama)
    allow_local_models: bool = False


def build_handler(settings: Settings) -> Handler:
    """Wire the run executor from settings (gateway, S3, tenant-scoped knowledge base)."""
    import uuid

    from bomagent_agent_worker.handler import RunExecutor
    from bomagent_agents import KbRetriever, Retriever
    from bomagent_common.storage import S3ObjectStore
    from bomagent_kb import KnowledgeBase
    from bomagent_llm.catalog import load_catalog
    from bomagent_llm.chat import ChatClient, GatewayChat
    from bomagent_llm.embeddings import EmbeddingClient, GatewayEmbeddings, HashingEmbeddings

    if settings.database_url is None:
        raise RuntimeError("BOMAGENT_DATABASE_URL is required")
    if not (settings.llm_gateway_url and settings.llm_gateway_key):
        raise RuntimeError("BOMAGENT_LLM_GATEWAY_URL and BOMAGENT_LLM_GATEWAY_KEY are required")
    if settings.allow_local_models and settings.is_production_like:
        raise RuntimeError("local models are not allowed in staging/prod")
    chat: ChatClient = GatewayChat(settings.llm_gateway_url, settings.llm_gateway_key)
    embedder: EmbeddingClient = (
        GatewayEmbeddings(
            settings.llm_gateway_url, settings.llm_gateway_key, settings.embedding_model
        )
        if settings.embedding_model != "fake-embedding"
        else HashingEmbeddings()
    )
    kb = KnowledgeBase(embedder)
    engine = make_engine(settings.database_url)

    def retriever_for(tenant_id: uuid.UUID, snapshot_id: str | None) -> Retriever:
        return KbRetriever(kb, engine, tenant_id, snapshot_id=snapshot_id)

    executor = RunExecutor(
        chat=chat,
        catalog=load_catalog(),
        store=S3ObjectStore(
            settings.files_bucket,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ),
        retriever_for=retriever_for,
        allow_local_models=settings.allow_local_models,
    )
    return executor.handle


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
            log.info("consumer_started", queue="runs")
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task
            shutdown_telemetry()

    return lifespan


async def _noop(message: Message) -> None:  # health-only mode (no queue configured)
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
        title="BOM Agent agent worker",
        readiness=readiness,
        lifespan=_make_lifespan(
            settings, handler or (build_handler(settings) if settings.queue_url else _noop)
        ),
        docs=False,
    )
