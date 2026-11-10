"""API test wiring: real Postgres (RLS), in-memory S3/SQS, dev tokens, fake model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from bomagent_agent_worker.handler import RunExecutor
from bomagent_agents import StaticRetriever
from bomagent_agents.simulators import simulate
from bomagent_api.app import Settings, create_app
from bomagent_api.auth import DevAuthenticator
from bomagent_api.routes import ApiServices
from bomagent_common.messaging import InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_ingest.handler import DesignIngestor
from bomagent_kb import KnowledgeBase
from bomagent_kb_indexer.handler import KbIndexer
from bomagent_llm.catalog import load_catalog
from bomagent_llm.embeddings import HashingEmbeddings
from bomagent_llm.fake import FakeChat

ROOT = Path(__file__).resolve().parents[3] / "evals" / "fixtures"
SECRET = "test-secret-0123456789-0123456789-abcdef"


@dataclass
class Stack:
    client: httpx.AsyncClient
    services: ApiServices
    auth: DevAuthenticator
    store: InMemoryObjectStore
    ingest: InMemoryQueue
    runs: InMemoryQueue
    ingestor: DesignIngestor
    executor: RunExecutor
    kb: InMemoryQueue
    indexer: KbIndexer

    def token(self, ctx, roles=("owner",)) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth.issue(ctx.tenant_id, ctx.actor_id, list(roles))}"
        }

    async def drain(self) -> None:
        """Run the workers on everything queued (same path as the consumer loop)."""
        for queue, handler in (
            (self.ingest, self.ingestor.handle),
            (self.runs, self.executor.handle),
            (self.kb, self.indexer.handle),
        ):
            for received in await queue.receive(max_messages=50):
                assert await process_one(queue, received, handler)


@pytest.fixture
async def stack(app_engine) -> AsyncIterator[Stack]:
    store, ingest, runs, kb = (
        InMemoryObjectStore(),
        InMemoryQueue(),
        InMemoryQueue(),
        InMemoryQueue(),
    )
    auth = DevAuthenticator(SECRET)
    services = ApiServices(
        engine=app_engine,
        store=store,
        ingest_queue=ingest,
        runs_queue=runs,
        authenticator=auth,
        catalog=load_catalog(),
        allow_local_models=True,
        sse_poll_seconds=0.01,
        kb_queue=kb,
    )
    app = create_app(Settings(environment="test"), services)
    retriever = StaticRetriever.from_directory(ROOT / "datasheets")
    executor = RunExecutor(
        chat=FakeChat(simulate),
        catalog=load_catalog(),
        store=store,
        retriever_for=lambda tenant, snap: retriever,
        allow_local_models=True,
        engine=app_engine,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        indexer = KbIndexer(KnowledgeBase(HashingEmbeddings()), app_engine, store)
        yield Stack(
            client,
            services,
            auth,
            store,
            ingest,
            runs,
            DesignIngestor(app_engine, store),
            executor,
            kb,
            indexer,
        )
