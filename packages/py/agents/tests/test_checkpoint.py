"""Tenant-scoped LangGraph checkpoints in PostgreSQL (RLS), used by the agent worker."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from bomagent_agents.checkpoint import TenantCheckpointSaver
from bomagent_agents.contracts import RunConfig, RunInput
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_cad import FileRef, parse_files
from bomagent_common.db import make_engine, tenant_transaction
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, kicad_project_paths

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


async def _run_row(engine, tenant_id: uuid.UUID) -> uuid.UUID:
    pid, rid = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(engine, tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime, model_id,"
                " created_by) VALUES (:r, :t, :p, 'B', 'langgraph_b', 'fake-closed', 'u')"
            ),
            {"r": rid, "t": tenant_id, "p": pid},
        )
    return rid


async def _count(engine, tenant_id: uuid.UUID, run_id: uuid.UUID) -> tuple[int, int]:
    async with tenant_transaction(engine, tenant_id) as conn:
        cps = await conn.scalar(
            text("SELECT count(*) FROM runs.graph_checkpoints WHERE run_id = :r"), {"r": run_id}
        )
        writes = await conn.scalar(
            text("SELECT count(*) FROM runs.graph_writes WHERE run_id = :r"), {"r": run_id}
        )
    return int(cps or 0), int(writes or 0)


@pytest.fixture(scope="module")
async def retriever():
    return await InMemoryRetriever.from_directory(FIXTURES / "datasheets")


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_runs_checkpoint_into_the_tenants_rows(app_engine, make_tenant, retriever, variant):
    a, b = await make_tenant(), await make_tenant()
    run_id = await _run_row(app_engine, a.tenant_id)
    design = parse_files([FileRef.from_path(p) for p in kicad_project_paths("pulse-ox")])
    run = RunInput(run_id=run_id, design=design, config=RunConfig(variant=variant))

    def factory(chk):
        return context_factory(
            FakeChat(heuristic_responder), retriever, tenant_id=str(a.tenant_id), checkpointer=chk
        )

    saver = TenantCheckpointSaver(app_engine, a.tenant_id)
    persisted = await runtime_for(variant, factory(lambda _run: saver)).run(run)
    in_memory = await runtime_for(variant, factory(None)).run(run)
    assert persisted.status == in_memory.status == "completed"
    assert [i.refdes for i in persisted.bom.items] == [i.refdes for i in in_memory.bom.items]

    checkpoints, _ = await _count(app_engine, a.tenant_id, run_id)
    assert checkpoints >= 2
    latest = await saver.aget_tuple({"configurable": {"thread_id": str(run_id)}})
    assert latest is not None
    assert latest.checkpoint["channel_values"]["items"]
    history = [t async for t in saver.alist({"configurable": {"thread_id": str(run_id)}})]
    assert len(history) == checkpoints
    assert history[0].checkpoint["id"] == latest.checkpoint["id"]  # newest first

    # another tenant sees nothing - neither through SQL nor through its own saver
    assert await _count(app_engine, b.tenant_id, run_id) == (0, 0)
    other = TenantCheckpointSaver(app_engine, b.tenant_id)
    assert await other.aget_tuple({"configurable": {"thread_id": str(run_id)}}) is None

    await saver.adelete_thread(str(run_id))
    assert await _count(app_engine, a.tenant_id, run_id) == (0, 0)


async def test_writes_roundtrip_and_cascade_with_the_run(app_engine, make_tenant, db_urls):
    a = await make_tenant()
    run_id = await _run_row(app_engine, a.tenant_id)
    saver = TenantCheckpointSaver(app_engine, a.tenant_id)
    base = {"configurable": {"thread_id": str(run_id), "checkpoint_ns": ""}}
    from langgraph.checkpoint.base import empty_checkpoint

    cp = empty_checkpoint()
    cp["channel_values"] = {"items": [{"refdes": ["R1"]}]}
    cfg = await saver.aput(base, cp, {"source": "input", "step": -1}, {"items": "1"})
    await saver.aput_writes(cfg, [("items", [{"refdes": ["R2"]}])], task_id="t1")
    await saver.aput_writes(cfg, [("items", [{"refdes": ["R3"]}])], task_id="t1")  # idempotent
    got = await saver.aget_tuple(cfg)
    assert got is not None
    assert got.pending_writes == [("t1", "items", [{"refdes": ["R2"]}])]
    assert got.metadata["step"] == -1
    assert [t async for t in saver.alist(base, filter={"source": "loop"})] == []

    # the app role cannot delete runs; retention/tenant deletion runs as the owner role
    owner = make_engine(db_urls.migrator)
    async with tenant_transaction(owner, a.tenant_id) as conn:  # FORCE RLS applies to owners
        await conn.execute(text("DELETE FROM runs.runs WHERE id = :r"), {"r": run_id})
    await owner.dispose()
    assert await _count(app_engine, a.tenant_id, run_id) == (0, 0)
