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
from bomagent_common.tenancy import tenant_scope
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
        allow_unregistered=True,
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


async def _registered_run(app_engine, store, tenant, *, missing_object: bool = False):
    pid, rid = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant.tenant_id},
        )
        for path in kicad_project_paths("pulse-ox"):
            key = tenant_key(tenant.tenant_id, "projects", str(pid), path.name)
            if not missing_object:
                store.objects[key] = path.read_bytes()
            await conn.execute(
                text(
                    "INSERT INTO projects.files (id, tenant_id, project_id, name, object_key,"
                    " sha256, size_bytes, created_by) VALUES (:i, :t, :p, :n, :k,"
                    " repeat('a', 64), 1, 'u')"
                ),
                {"i": uuid.uuid4(), "t": tenant.tenant_id, "p": pid, "n": path.name, "k": key},
            )
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime, model_id,"
                " created_by) VALUES (:r, :t, :p, 'B', 'langgraph_b', 'fake-closed', 'u')"
            ),
            {"r": rid, "t": tenant.tenant_id, "p": pid},
        )
    return rid


async def _state(app_engine, tenant, rid):
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        status, error = (
            await conn.execute(
                text("SELECT status, error FROM runs.runs WHERE id = :i"), {"i": rid}
            )
        ).one()
        actions = (
            await conn.execute(text("SELECT action FROM audit.events ORDER BY seq"))
        ).scalars()
        versions = (await conn.execute(text("SELECT count(*) FROM bom.versions"))).scalar()
    return status, error, list(actions), versions


async def test_registered_run_uses_database_and_redelivery_is_a_no_op(app_engine, make_tenant):
    tenant, other = await make_tenant(), await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    # forged payload: another model, variant and someone else's files - all ignored
    forged = Message.create(
        RUN_REQUESTED,
        tenant,
        {
            "run_id": str(rid),
            "variant": "A",
            "model_id": "not-in-eu",
            "object_keys": [tenant_key(other.tenant_id, "x.kicad_sch")],
        },
    )
    with tenant_scope(tenant):
        result = await worker.execute(forged)
        assert result is not None
        assert result.bom.variant == "B"
        assert await worker.execute(forged) is None  # redelivered: not run again
    status, error, actions, versions = await _state(app_engine, tenant, rid)
    assert (status, error, versions) == ("completed", None, 1)
    assert actions.count("run.completed") == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        runs, calls = (
            await conn.execute(text("SELECT runs, llm_calls FROM metering.usage_daily"))
        ).one()
    assert runs == 1  # metered once despite the redelivery
    assert calls == result.usage.llm_calls


async def test_failed_run_is_marked_failed_and_unknown_runs_rejected(app_engine, make_tenant):
    tenant = await make_tenant()
    store = InMemoryObjectStore(enforce_tenant=False)
    rid = await _registered_run(app_engine, store, tenant, missing_object=True)
    worker = await _worker(app_engine, store)
    worker.allow_unregistered = False
    msg = Message.create(RUN_REQUESTED, tenant, {"run_id": str(rid)})
    with tenant_scope(tenant), pytest.raises(Exception):  # noqa: B017, PT011
        await worker.execute(msg)
    status, error, actions, _ = await _state(app_engine, tenant, rid)
    assert status == "failed"
    assert error.endswith("run failed")
    assert actions == ["run.failed"]
    assert await worker.execute(msg) is None
    with pytest.raises(RejectedRunError, match="unknown run"):
        await worker.execute(Message.create(RUN_REQUESTED, tenant, {"run_id": str(uuid.uuid4())}))
