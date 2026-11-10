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
    result = await sweep(app_engine, platform_engine, {}, run_timeout_s=3600)
    assert result["reaped"] >= 1
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
