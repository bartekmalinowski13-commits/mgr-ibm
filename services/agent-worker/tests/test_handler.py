"""agent-worker: run.requested -> design from S3 -> variant -> results + audit."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from bomagent_agent_worker.app import Settings, build_handler
from bomagent_agent_worker.handler import RUN_REQUESTED, RejectedRunError, RunWorker
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, Message, process_one
from bomagent_common.storage import InMemoryObjectStore, tenant_key
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, kicad_project_paths
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


async def _worker(app_engine, store):
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    return RunWorker(
        engine=app_engine,
        store=store,
        chat=FakeChat(heuristic_responder),
        kb=make_kb(),
        retriever_factory=lambda t, s: retriever,
    )


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_run_requested_produces_bom_trace_and_audit(app_engine, make_tenant, variant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    keys = []
    for path in kicad_project_paths("pulse-ox"):
        key = tenant_key(tenant.tenant_id, "projects", "p1", path.name)
        store.objects[key] = path.read_bytes()
        keys.append(key)
    run_id = uuid.uuid4()
    worker = await _worker(app_engine, store)
    queue = InMemoryQueue()
    await queue.send(
        Message.create(
            RUN_REQUESTED, tenant, {"run_id": str(run_id), "variant": variant, "object_keys": keys}
        )
    )
    (item,) = await queue.receive()
    assert await process_one(queue, item, worker.handle)
    bom = json.loads(store.objects[tenant_key(tenant.tenant_id, "runs", str(run_id), "bom.json")])
    assert bom["variant"] == variant
    assert bom["items"]
    assert tenant_key(tenant.tenant_id, "runs", str(run_id), "trace.json") in store.objects
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        action = (await conn.execute(text("SELECT action FROM audit.events"))).scalar()
    assert action == "run.completed"


async def test_foreign_keys_are_rejected_and_other_messages_ignored(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    worker = await _worker(app_engine, InMemoryObjectStore(enforce_tenant=False))
    with pytest.raises(RejectedRunError):
        await worker.execute(
            Message.create(
                RUN_REQUESTED,
                a,
                {
                    "run_id": str(uuid.uuid4()),
                    "variant": "B",
                    "object_keys": [tenant_key(b.tenant_id, "x.kicad_sch")],
                },
            )
        )
    with pytest.raises(RejectedRunError, match="does not implement"):
        await worker.execute(
            Message.create(
                RUN_REQUESTED,
                a,
                {
                    "run_id": str(uuid.uuid4()),
                    "variant": "B",
                    "runtime": "langgraph_a",
                    "object_keys": [tenant_key(a.tenant_id, "x.kicad_sch")],
                },
            )
        )
    await worker.handle(Message.create("other.type", a))


def test_build_handler_wiring(db_urls):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        build_handler(Settings(environment="test"))
    fake = build_handler(Settings(environment="test", database_url=db_urls.app))
    assert isinstance(fake.__self__.chat, FakeChat)
    real = build_handler(
        Settings(
            environment="test",
            database_url=db_urls.app,
            llm_gateway_url="http://gw",
            llm_gateway_key="k",
        )
    )
    assert type(real.__self__.chat).__name__ == "GatewayChat"
