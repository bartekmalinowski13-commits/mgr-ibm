"""Organisation data export (SEC-14): API + builder, real PostgreSQL (CI only), tenant isolation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.org_export import MAX_EXPORTS_PER_DAY, archive_key
from bomagent_common.storage import InMemoryObjectStore
from bomagent_kb_indexer.handler import KbIndexer
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine) -> None:
        self.store = InMemoryObjectStore(enforce_tenant=False)
        self.kb_queue = InMemoryQueue()
        self.app_engine = app_engine
        self.app = create_app(
            Settings(environment="test", auth_mode="local"),
            engine=app_engine,
            platform_engine=platform_engine,
            store=self.store,
            queues={"kb": self.kb_queue},
            kb=make_kb(),
        )
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://a")

    async def login(self, sub: str) -> dict:
        resp = await self.c.post(
            "/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu", "email_verified": True}
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def org(self, auth: dict, slug: str) -> dict:
        resp = await self.c.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert resp.status_code == 201, resp.text
        return auth | {"X-Org-Id": resp.json()["id"]}

    async def run_worker(self) -> None:
        indexer = KbIndexer(kb=make_kb(), app_engine=self.app_engine, tenant_store=self.store)
        for received in await self.kb_queue.receive():
            await indexer.handle(received.message)
            await self.kb_queue.ack(received)

    def url(self, headers: dict, suffix: str = "") -> str:
        return f"/v1/organizations/{headers['X-Org-Id']}/export{suffix}"


@pytest.fixture
def env(app_engine, platform_engine) -> Env:
    return Env(app_engine, platform_engine)


async def test_export_end_to_end(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"ex-{s}")
    proj = await env.c.post("/v1/projects", headers=owner, json={"name": f"Pump {s}"})
    assert proj.status_code == 201, proj.text

    started = await env.c.post(env.url(owner), headers=owner)
    assert started.status_code == 202, started.text
    job = started.json()
    assert job["status"] == "queued"
    early = await env.c.get(env.url(owner, f"/{job['id']}/download"), headers=owner)
    assert early.status_code == 409

    await env.run_worker()
    done = (await env.c.get(env.url(owner, f"/{job['id']}"), headers=owner)).json()
    assert done["status"] == "completed", done
    assert done["counts"]["projects"] >= 1

    link = await env.c.get(env.url(owner, f"/{job['id']}/download"), headers=owner)
    assert link.status_code == 200
    assert link.json()["expires_in_s"] <= 900
    org_id = uuid.UUID(owner["X-Org-Id"])
    blob = env.store.objects[archive_key(org_id, uuid.UUID(job["id"]))]
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "projects.json", "audit_events.jsonl"} <= names
        projects = json.loads(zf.read("projects.json"))
        assert [p["name"] for p in projects if p["sample_key"] is None] == [f"Pump {s}"]
        events = [json.loads(line) for line in zf.read("audit_events.jsonl").splitlines()]
        assert {e["action"] for e in events} >= {"org.created", "org.export.requested"}
        assert {e["tenant_id"] for e in events if "tenant_id" in e} <= {str(org_id)}

    audit = (await env.c.get("/v1/audit-events?limit=50", headers=owner)).json()["items"]
    actions = {e["action"] for e in audit}
    assert {"org.export.requested", "org.export.completed", "org.export.downloaded"} <= actions


async def test_only_owner_or_admin_may_export(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"ro-{s}")
    invite = await env.c.post(
        "/v1/invitations", headers=owner, json={"email": f"v-{s}@x.eu", "roles": ["viewer"]}
    )
    viewer = await env.login(f"v-{s}")
    ok = await env.c.post(
        "/v1/invitations/accept", headers=viewer, json={"token": invite.json()["token"]}
    )
    assert ok.status_code == 200, ok.text
    viewer = viewer | {"X-Org-Id": owner["X-Org-Id"]}
    denied = await env.c.post(env.url(owner), headers=viewer)
    assert denied.status_code == 403
    assert denied.json()["type"].endswith("forbidden-action")


async def test_export_is_tenant_isolated(env):
    """Another organisation's owner can neither start, read nor download our export."""
    s = uuid.uuid4().hex[:6]
    a = await env.org(await env.login(f"a-{s}"), f"iso-a-{s}")
    b = await env.org(await env.login(f"b-{s}"), f"iso-b-{s}")
    job = (await env.c.post(env.url(a), headers=a)).json()
    await env.run_worker()

    # B addresses A's organisation id in the path: 404, same as for an unknown organisation
    assert (
        await env.c.post(f"/v1/organizations/{a['X-Org-Id']}/export", headers=b)
    ).status_code == 404
    # B uses its own organisation but A's job id: the key is derived from B's tenant -> 404
    for suffix in ("", "/download"):
        resp = await env.c.get(env.url(b, f"/{job['id']}{suffix}"), headers=b)
        assert resp.status_code == 404, resp.text
    # B using A's X-Org-Id is not a member
    forged = b | {"X-Org-Id": a["X-Org-Id"]}
    assert (await env.c.get(env.url(a, f"/{job['id']}"), headers=forged)).status_code == 403

    # B's own export never contains A's data
    mine = (await env.c.post(env.url(b), headers=b)).json()
    await env.run_worker()
    blob = env.store.objects[archive_key(uuid.UUID(b["X-Org-Id"]), uuid.UUID(mine["id"]))]
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read("audit_events.jsonl").decode() + zf.read("manifest.json").decode()
    assert a["X-Org-Id"] not in raw
    assert f"iso-a-{s}" not in raw


async def test_export_is_rate_limited(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"rl-{s}")
    for _ in range(MAX_EXPORTS_PER_DAY):
        assert (await env.c.post(env.url(owner), headers=owner)).status_code == 202
    over = await env.c.post(env.url(owner), headers=owner)
    assert over.status_code == 429
    assert over.json()["type"].endswith("quota-exceeded")


async def test_idempotency_key_replays_the_same_job(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"id-{s}")
    headers = owner | {"Idempotency-Key": f"export-{s}-1"}
    first = await env.c.post(env.url(owner), headers=headers)
    again = await env.c.post(env.url(owner), headers=headers)
    assert first.json()["id"] == again.json()["id"]
    async with tenant_transaction(env.app_engine, uuid.UUID(owner["X-Org-Id"])) as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM audit.events WHERE action = 'org.export.requested'")
            )
        ).scalar()
    assert n == 1
