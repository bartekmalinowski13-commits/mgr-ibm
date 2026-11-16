"""Outbox (queue messages committed with their rows) and the stuck-run reaper."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_api.maintenance import sweep
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, Message
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.api import mark_files_parsed
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


class BrokenQueue(InMemoryQueue):
    def __init__(self) -> None:
        super().__init__()
        self.down = True

    async def send(self, message: Message) -> None:
        if self.down:
            raise ConnectionError("queue unavailable")
        await super().send(message)


async def test_queue_outage_is_bridged_by_the_outbox(app_engine, platform_engine):
    queues = {"ingest": BrokenQueue(), "runs": BrokenQueue()}
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues=queues,
        kb=make_kb(),
    )
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")
    s = uuid.uuid4().hex[:6]
    tok = (await c.post("/v1/dev/token", json={"sub": f"o-{s}", "email": f"o-{s}@x.eu"})).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    org = await c.post("/v1/organizations", headers=auth, json={"name": s, "slug": f"ob-{s}"})
    owner = auth | {"X-Org-Id": org.json()["id"]}
    pid = (await c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    up = await c.post(
        f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.kicad_sch", b"x")}
    )
    assert up.status_code == 201  # committed although the queue is down
    await mark_files_parsed(app_engine, owner["X-Org-Id"])
    run = await c.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    assert run.status_code == 202
    assert len(queues["ingest"]) == len(queues["runs"]) == 0

    for q in queues.values():
        q.down = False
    sent = await sweep(app_engine, platform_engine, queues, run_timeout_s=3600, outbox_grace_s=0)
    assert sent["sent"] >= 2
    assert len(queues["ingest"]) == 1
    assert len(queues["runs"]) == 1
    (item,) = await queues["runs"].receive()
    assert item.message.payload["run_id"] == run.json()["id"]
    again = await sweep(app_engine, platform_engine, queues, run_timeout_s=3600, outbox_grace_s=0)
    assert len(queues["runs"]) + again["sent"] <= 1  # nothing is sent twice


async def test_stuck_runs_are_reaped(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    pid, stuck, fresh = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant.tenant_id},
        )
        for rid, age in ((stuck, "2 hours"), (fresh, "1 minute")):
            await conn.execute(
                text(
                    "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime,"
                    " model_id, created_by, status, started_at) VALUES (:r, :t, :p, 'B',"
                    " 'langgraph_b', 'fake-closed', 'u', 'running',"
                    " now() - CAST(:age AS interval))"
                ),
                {"r": rid, "t": tenant.tenant_id, "p": pid, "age": age},
            )
    from bomagent_common.config import ServiceSettings
    from bomagent_common.telemetry import configure_telemetry, metric_reader

    configure_telemetry(ServiceSettings(service_name="test", environment="test"))

    def failed_b() -> float:
        data = metric_reader().get_metrics_data()
        return sum(
            float(dp.value)
            for rm in (data.resource_metrics if data else [])
            for sm in rm.scope_metrics
            for m in sm.metrics
            if m.name == "bomagent_runs_total"
            for dp in m.data.data_points
            if dict(dp.attributes) == {"status": "failed", "variant": "B"}
        )

    before = failed_b()
    result = await sweep(app_engine, platform_engine, {}, run_timeout_s=3600)
    assert result["reaped"] >= 1
    assert failed_b() - before >= 1  # a reaped run is a failed run in the metrics too
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        states = {
            r.id: r.status for r in await conn.execute(text("SELECT id, status FROM runs.runs"))
        }
        actions = (await conn.execute(text("SELECT action FROM audit.events"))).scalars().all()
    assert states == {stuck: "failed", fresh: "running"}
    assert actions == ["run.failed"]


async def test_stale_queued_runs_are_reaped(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    pid, rid = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant.tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime, model_id,"
                " created_by, created_at) VALUES (:r, :t, :p, 'B', 'langgraph_b',"
                " 'fake-closed', 'u', now() - interval '3 days')"
            ),
            {"r": rid, "t": tenant.tenant_id, "p": pid},
        )
    await sweep(app_engine, platform_engine, {}, run_timeout_s=3600)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        status = (
            await conn.execute(text("SELECT status FROM runs.runs WHERE id = :i"), {"i": rid})
        ).scalar()
    assert status == "failed"


async def test_sweep_exports_one_anchor_per_tenant_and_day_and_verify_uses_it(
    app_engine, platform_engine, make_tenant, tmp_path
):
    """The head of the audit chain is exported once a day to write-once storage; a stored
    anchor that no longer matches the chain marks it broken (rewritten history)."""
    from bomagent_common.audit import ChainAnchor, chain_head, verify_chain
    from bomagent_common.audit_anchor import FileAnchorSink, load_anchors

    tenant = await make_tenant()
    sink = FileAnchorSink(tmp_path)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": uuid.uuid4(), "t": tenant.tenant_id},
        )
        from bomagent_common.audit import AuditEvent, emit_audit

        await emit_audit(
            conn,
            AuditEvent(action="project.created", object_type="p", object_id="1"),
            tenant,
        )
        head = await chain_head(conn, tenant.tenant_id)
    assert head is not None

    for _ in range(2):  # a second sweep the same day must not write again
        await sweep(app_engine, platform_engine, {}, run_timeout_s=3600, anchor_sink=sink)
    anchors = await load_anchors(sink, tenant.tenant_id)
    assert anchors == [head]
    assert len(await sink.list(f"audit-anchors/{tenant.tenant_id}/")) == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        assert (await verify_chain(conn, tenant.tenant_id, anchors)).ok
        forged = [ChainAnchor(head.seq, "0" * 64)]
        assert (await verify_chain(conn, tenant.tenant_id, forged)).first_broken_seq == head.seq
