"""``BOMAGENT_QUEUE_BACKEND``: SQS (default, AWS) or the PostgreSQL queue (Supabase pilot)."""

from __future__ import annotations

import asyncio
import importlib
import uuid

import httpx
import pytest
from moto import mock_aws

from bomagent_common.config import ServiceSettings
from bomagent_common.messaging import (
    MAX_RECEIVE_COUNT,
    QUEUE_VISIBILITY_S,
    Message,
    PostgresQueue,
    SqsQueue,
    make_queue,
)
from bomagent_testing.data import KICAD_FIXTURES

WORKERS = {
    "ingest": "bomagent_ingest.app",
    "runs": "bomagent_agent_worker.app",
    "kb": "bomagent_kb_indexer.app",
}


def test_default_backend_is_sqs():
    assert ServiceSettings().queue_backend == "sqs"


def test_backend_and_platform_url_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("BOMAGENT_QUEUE_BACKEND", "postgres")
    monkeypatch.setenv("BOMAGENT_DATABASE_HOST", "db.example.eu")
    monkeypatch.setenv("BOMAGENT_PLATFORM_DATABASE_PASSWORD", "p@ss")
    settings = ServiceSettings()
    assert settings.queue_backend == "postgres"
    assert settings.platform_database_url is not None
    assert settings.platform_database_url.startswith(
        "postgresql+psycopg://bomagent_platform:p%40ss@db.example.eu:5432/bomagent?"
    )


def test_make_queue_sqs_by_default():
    with mock_aws():
        queue = make_queue(ServiceSettings(), "runs", sqs_url="https://sqs.example/q")
    assert isinstance(queue, SqsQueue)
    assert make_queue(ServiceSettings(), "runs", sqs_url=None) is None


def test_make_queue_postgres_uses_the_aws_like_redrive_settings():
    settings = ServiceSettings(queue_backend="postgres")
    queue = make_queue(settings, "runs", sqs_url="ignored")
    assert isinstance(queue, PostgresQueue)
    assert queue.name == "runs"
    assert queue._visibility == QUEUE_VISIBILITY_S["runs"] == 3600
    assert queue._max_receive == MAX_RECEIVE_COUNT == 5


@pytest.mark.parametrize("module", ["bomagent_api.app"])
def test_api_keeps_sqs_queues_by_default(module):
    mod = importlib.import_module(module)
    with mock_aws():
        app = mod.create_app(
            mod.Settings(
                environment="test",
                auth_mode="local",
                ingest_queue_url="https://sqs.example/ingest",
                runs_queue_url="https://sqs.example/runs",
                kb_queue_url="https://sqs.example/kb",
            )
        )
    assert {type(q) for q in app.state.queues.values()} == {SqsQueue}


@pytest.mark.integration
async def test_api_sends_to_the_postgres_queue(app_engine, platform_engine):
    from bomagent_api.app import Settings, create_app
    from bomagent_common.storage import InMemoryObjectStore
    from bomagent_testing.kb import make_kb

    app = create_app(
        Settings(environment="test", auth_mode="local", queue_backend="postgres"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        kb=make_kb(),
    )
    queues = app.state.queues
    assert {type(q) for q in queues.values()} == {PostgresQueue}
    assert set(queues) == {"ingest", "runs", "kb"}
    s = uuid.uuid4().hex[:6]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        token = await client.post("/v1/dev/token", json={"sub": f"q-{s}", "email": f"q-{s}@x.eu"})
        auth = {"Authorization": f"Bearer {token.json()['access_token']}"}
        org = await client.post("/v1/organizations", headers=auth, json={"name": s, "slug": s})
        auth["X-Org-Id"] = org.json()["id"]
        project = await client.post("/v1/projects", headers=auth, json={"name": "p"})
        path = next(KICAD_FIXTURES.glob("*/*.kicad_sch"))
        resp = await client.post(
            f"/v1/projects/{project.json()['id']}/files",
            headers=auth,
            files={"file": (path.name, path.read_bytes())},
        )
        assert resp.status_code == 201, resp.text
    consumer = PostgresQueue("ingest", consumer_engine=platform_engine)
    items = await consumer.receive(max_messages=50, wait_seconds=0)
    mine = [i for i in items if str(i.message.tenant_id) == org.json()["id"]]
    assert [i.message.type for i in mine] == ["file.uploaded"]
    for item in items:
        await consumer.ack(item)


@pytest.mark.integration
@pytest.mark.parametrize("queue_name", sorted(WORKERS))
async def test_workers_consume_the_postgres_queue(queue_name, db_urls, app_engine, make_tenant):
    mod = importlib.import_module(WORKERS[queue_name])
    settings = mod.Settings(
        environment="test",
        queue_backend="postgres",
        queue_poll_interval_s=0.05,
        queue_wait_seconds=1,
        database_url=db_urls.app,
        platform_database_url=db_urls.platform,
    )
    assert settings.queue_name == queue_name
    got: list[Message] = []
    done = asyncio.Event()

    async def handler(message: Message) -> None:
        if message.tenant_id == tenant.tenant_id:  # the queue table is shared by the session
            got.append(message)
            done.set()

    tenant = await make_tenant()
    app = mod.create_app(settings, handler=handler)
    async with app.router.lifespan_context(app):
        sent = Message.create("probe", tenant, {"q": queue_name})
        await PostgresQueue(queue_name, producer_engine=app_engine).send(sent)
        await asyncio.wait_for(done.wait(), timeout=10)
    assert [m.message_id for m in got] == [sent.message_id]


def test_workers_need_the_platform_role_for_the_postgres_queue():
    mod = importlib.import_module(WORKERS["ingest"])
    with pytest.raises(RuntimeError, match="PLATFORM_DATABASE_URL"):
        mod.create_app(
            mod.Settings(
                environment="test",
                queue_backend="postgres",
                database_url="postgresql+psycopg://u:p@127.0.0.1:1/x",
            ),
            handler=lambda m: asyncio.sleep(0),
        )
