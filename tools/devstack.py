"""Local all-in-one stack for UI development and Playwright E2E (never deployed).

One process: a fresh PostgreSQL database with all migrations, the API (mock IdP, local
environment) and the ingest and agent workers consuming in-memory queues with the fake
LLM. Needs only PostgreSQL 16 + pgvector (no Docker, no AWS emulators).

    BOMAGENT_DEV_ADMIN_URL=postgresql+psycopg://postgres:...@localhost:5432/postgres \
        uv run python tools/devstack.py --port 8000

Note: role passwords are (re)set on start, like the pytest fixtures do; do not run it
while the integration tests run against the same server. The database is dropped on exit.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import secrets
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine, make_url, text

from bomagent_agent_worker.handler import RunWorker
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_api.app import Settings, create_app
from bomagent_common.db import make_engine
from bomagent_common.messaging import Handler, InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_ingest.handler import IngestWorker
from bomagent_kb import KnowledgeBase
from bomagent_kb_indexer.handler import KbIndexer
from bomagent_llm.chat import FakeChat
from bomagent_llm.embeddings import HashingEmbeddings
from bomagent_migrations import APP_ROLE, PLATFORM_ROLE, bootstrap, upgrade

ROOT = Path(__file__).resolve().parents[1]


def create_database(admin_url: str) -> tuple[str, dict[str, str], str]:
    base = make_url(admin_url).set(drivername="postgresql+psycopg")
    name = f"bomagent_dev_{secrets.token_hex(3)}"
    pwds = {r: secrets.token_hex(16) for r in ("bomagent_migrator", APP_ROLE, PLATFORM_ROLE)}
    bootstrap(base.render_as_string(hide_password=False), pwds)
    eng = create_engine(base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" OWNER bomagent_migrator'))
    eng.dispose()
    db = base.set(database=name)
    eng = create_engine(db.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO {APP_ROLE}, {PLATFORM_ROLE}'))
    eng.dispose()
    urls = {
        role: db.set(username=role, password=pwds[role]).render_as_string(hide_password=False)
        for role in pwds
    }
    upgrade(urls["bomagent_migrator"])
    return name, urls, base.render_as_string(hide_password=False)


def drop_database(admin_url: str, name: str) -> None:
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    eng.dispose()


async def consume(queue: InMemoryQueue, handler: Handler, stop: asyncio.Event) -> None:
    while not stop.is_set():
        batch = await queue.receive(max_messages=10)
        for item in batch:
            await process_one(queue, item, handler)
        if not batch:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=0.2)


async def serve(urls: dict[str, str], port: int) -> None:
    engine = make_engine(urls[APP_ROLE])
    platform = make_engine(urls[PLATFORM_ROLE], pool_size=2)
    store = InMemoryObjectStore(enforce_tenant=False)
    queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue(), "kb": InMemoryQueue()}
    kb = KnowledgeBase(HashingEmbeddings())
    app = create_app(
        Settings(environment="local", auth_mode="local", maintenance_interval_s=5),
        engine=engine,
        platform_engine=platform,
        store=store,
        queues=queues,  # type: ignore[arg-type]
        kb=kb,
    )
    retriever = await InMemoryRetriever.from_directory(ROOT / "evals/fixtures/datasheets")
    runs = RunWorker(
        engine=engine,
        store=store,
        chat=FakeChat(heuristic_responder),
        kb=kb,
        retriever_factory=lambda tenant, snapshot: retriever,
    )
    stop = asyncio.Event()
    workers = [
        asyncio.create_task(consume(queues["ingest"], IngestWorker(engine, store).handle, stop)),
        asyncio.create_task(consume(queues["runs"], runs.handle, stop)),
        asyncio.create_task(
            consume(
                queues["kb"],
                KbIndexer(kb=kb, app_engine=engine, tenant_store=store).handle,
                stop,
            )
        ),
    ]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    try:
        await server.serve()
    finally:
        stop.set()
        await asyncio.gather(*workers)
        await engine.dispose()
        await platform.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("BOMAGENT_PORT", "8000")))
    args = parser.parse_args()
    admin = os.environ.get("BOMAGENT_DEV_ADMIN_URL") or os.environ.get("BOMAGENT_TEST_DATABASE_URL")
    if not admin:
        raise SystemExit("set BOMAGENT_DEV_ADMIN_URL (PostgreSQL admin URL)")
    name, urls, admin_url = create_database(admin)
    print(f"devstack: database {name}, API on http://127.0.0.1:{args.port}", flush=True)
    try:
        asyncio.run(serve(urls, args.port))
    finally:
        drop_database(admin_url, name)


if __name__ == "__main__":
    main()
