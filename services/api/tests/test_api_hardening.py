"""Hardening found in the API review: unexpected errors, cursors, KB quota and dedupe,
tracing of database and background writes, sweep isolation, member pages, export cap."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy import text

from bomagent_api import maintenance, plans
from bomagent_api.app import SECURITY_HEADERS, Settings, create_app
from bomagent_api.services import exports as export_service
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.storage import InMemoryObjectStore
from bomagent_common.telemetry import configure_telemetry
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine) -> None:
        self.store = InMemoryObjectStore(enforce_tenant=False)
        self.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue(), "kb": InMemoryQueue()}
        self.engine = app_engine
        self.app = create_app(
            Settings(environment="test", auth_mode="local"),
            engine=app_engine,
            platform_engine=platform_engine,
            store=self.store,
            queues=self.queues,
            kb=make_kb(),
        )
        self.c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://a",
        )

    async def org(self, prefix: str) -> dict[str, str]:
        sub = f"{prefix}-{uuid.uuid4().hex[:8]}"
        tok = (
            await self.c.post(
                "/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu", "email_verified": True}
            )
        ).json()
        auth = {"Authorization": f"Bearer {tok['access_token']}"}
        org = await self.c.post("/v1/organizations", headers=auth, json={"name": sub, "slug": sub})
        assert org.status_code == 201, org.text
        return auth | {"X-Org-Id": org.json()["id"]}

    def kb_objects(self, headers: dict[str, str]) -> list[str]:
        prefix = f"tenants/{headers['X-Org-Id']}/kb/"
        return [k for k in self.store.objects if k.startswith(prefix)]


@pytest.fixture
def env(app_engine, platform_engine) -> Env:
    return Env(app_engine, platform_engine)


def _assert_problem(resp: httpx.Response, status: int, slug: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"].endswith(f"/{slug}")


# ---------------------------------------------------------------- I1 unexpected errors
async def test_unexpected_error_is_problem_json_with_security_headers(env):
    async def boom() -> None:
        raise RuntimeError("secret internals: /srv/app.py line 42")

    env.app.add_api_route("/v1/__boom", boom)
    resp = await env.c.get("/v1/__boom")
    _assert_problem(resp, 500, "internal")
    assert "secret internals" not in resp.text
    assert "Traceback" not in resp.text
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers.get(name) == value, name


# ---------------------------------------------------------------- I2 audit cursor
@pytest.mark.parametrize("cursor", ["²", "abc", "-1", "%F0%9F%92%A5", "MTIz"])
async def test_malformed_audit_cursor_is_400(env, cursor):
    owner = await env.org("aud")
    resp = await env.c.get(f"/v1/audit-events?cursor={cursor}", headers=owner)
    _assert_problem(resp, 400, "invalid-cursor")


async def test_audit_cursor_is_opaque_and_pages(env):
    owner = await env.org("aud")
    for i in range(3):
        assert (
            await env.c.post("/v1/projects", headers=owner, json={"name": f"p{i}"})
        ).status_code == 201
    first = (await env.c.get("/v1/audit-events?limit=2", headers=owner)).json()
    assert first["next_cursor"]
    assert not first["next_cursor"].isdigit()
    second = (
        await env.c.get(f"/v1/audit-events?limit=2&cursor={first['next_cursor']}", headers=owner)
    ).json()
    seen = [e["seq"] for e in first["items"]] + [e["seq"] for e in second["items"]]
    assert len(seen) == len(set(seen)) == 4  # org.created + 3 project.created
    assert seen == sorted(seen, reverse=True)


# ---------------------------------------------------------------- I3 KB storage quota
@pytest.fixture
def tiny_storage(monkeypatch):
    plan = dataclasses.replace(plans.PLANS["pilot"], storage_bytes=100)
    monkeypatch.setitem(plans.PLANS, "pilot", plan)


async def test_kb_upload_honours_the_storage_quota(env, tiny_storage):
    owner = await env.org("kbq")
    resp = await env.c.post(
        "/v1/kb/documents", headers=owner, files={"file": ("big.md", b"x" * 101)}
    )
    _assert_problem(resp, 429, "quota-exceeded")
    assert env.kb_objects(owner) == []
    assert len(env.queues["kb"]) == 0


async def test_kb_documents_and_design_files_share_the_quota(env, tiny_storage):
    owner = await env.org("kbq")
    ok = await env.c.post("/v1/kb/documents", headers=owner, files={"file": ("a.md", b"a" * 60)})
    assert ok.status_code == 201, ok.text
    pid = (await env.c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    over = await env.c.post(
        f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.kicad_sch", b"s" * 60)}
    )
    _assert_problem(over, 429, "quota-exceeded")


# ---------------------------------------------------------------- I4 KB duplicates
async def test_concurrent_identical_kb_uploads_create_one_document(env):
    owner = await env.org("kbd")
    body = f"# Datasheet {uuid.uuid4()}\nsame content".encode()

    async def upload() -> httpx.Response:
        return await env.c.post("/v1/kb/documents", headers=owner, files={"file": ("d.md", body)})

    responses = await asyncio.gather(*(upload() for _ in range(4)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 200, 200, 201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(env.queues["kb"]) == 1
    assert len(env.kb_objects(owner)) == 1


async def test_duplicate_while_pending_is_not_reindexed(env):
    owner = await env.org("kbd")
    body = b"pending duplicate"
    first = await env.c.post("/v1/kb/documents", headers=owner, files={"file": ("d.md", body)})
    assert first.status_code == 201
    again = await env.c.post("/v1/kb/documents", headers=owner, files={"file": ("e.md", body)})
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert len(env.queues["kb"]) == 1
    [key] = env.kb_objects(owner)
    async with tenant_transaction(env.engine, uuid.UUID(owner["X-Org-Id"])) as conn:
        stored = (
            await conn.execute(
                text("SELECT object_key FROM kb.documents WHERE id = :i"), {"i": first.json()["id"]}
            )
        ).scalar()
    assert stored == key


# ---------------------------------------------------------------- I5 tracing
async def test_database_statements_are_traced(env):
    exporter = InMemorySpanExporter()
    configure_telemetry(Settings(environment="test"), extra_exporter=exporter)
    owner = await env.org("otel")
    assert (await env.c.get("/v1/projects", headers=owner)).status_code == 200
    db_spans = [s for s in exporter.get_finished_spans() if s.attributes.get("db.system")]
    assert db_spans, [(s.name, dict(s.attributes)) for s in exporter.get_finished_spans()][:8]


async def test_sweep_and_outbox_delivery_are_traced(env, platform_engine):
    exporter = InMemorySpanExporter()
    configure_telemetry(Settings(environment="test"), extra_exporter=exporter)
    owner = await env.org("otel")
    await maintenance.sweep(env.engine, platform_engine, env.queues, run_timeout_s=3600)
    spans = exporter.get_finished_spans()
    tenant_spans = [s for s in spans if s.name == "maintenance.sweep_tenant"]
    assert owner["X-Org-Id"] in {s.attributes.get("tenant.id") for s in tenant_spans}
    deliver = [s for s in spans if s.name == "outbox.deliver"]
    assert deliver
    assert all(s.kind == SpanKind.PRODUCER for s in deliver)
    assert deliver[0].attributes.get("messaging.operation.type") == "send"


# ---------------------------------------------------------------- M7 sweep isolation
async def test_sweep_continues_past_a_failing_tenant(env, platform_engine, monkeypatch):
    bad = uuid.UUID((await env.org("swp"))["X-Org-Id"])
    good = uuid.UUID((await env.org("swp"))["X-Org-Id"])
    seen: list[uuid.UUID] = []
    original = maintenance.expire_rate_windows

    async def flaky(engine, tenant_id, *args, **kwargs):
        seen.append(tenant_id)
        if tenant_id == bad:
            raise RuntimeError("tenant broken")
        return await original(engine, tenant_id, *args, **kwargs)

    monkeypatch.setattr(maintenance, "expire_rate_windows", flaky)
    monkeypatch.setattr(maintenance, "reap_stuck_runs", _reap_failing_for(bad))
    await maintenance.sweep(env.engine, platform_engine, env.queues, run_timeout_s=3600)
    assert good in seen


def _reap_failing_for(bad: uuid.UUID):
    original = maintenance.reap_stuck_runs

    async def reap(engine, tenant_id, timeout_s):
        if tenant_id == bad:
            raise RuntimeError("reaper broken for one tenant")
        return await original(engine, tenant_id, timeout_s)

    return reap


# ---------------------------------------------------------------- M8 member pages
async def test_member_list_is_paginated(env):
    owner = await env.org("mem")
    tid = owner["X-Org-Id"]
    async with tenant_transaction(env.engine, uuid.UUID(tid)) as conn:
        for i in range(4):
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email, roles)"
                    " VALUES (:t, :s, :e, ARRAY['viewer'])"
                ),
                {"t": tid, "s": f"m{i}-{tid}", "e": f"m{i}@x.eu"},
            )
    subs: list[str] = []
    cursor = None
    pages = 0
    while True:
        url = "/v1/members?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = (await env.c.get(url, headers=owner)).json()
        subs += [m["user_sub"] for m in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert pages == 3
    assert len(subs) == len(set(subs)) == 5
    bad = await env.c.get("/v1/members?cursor=nope", headers=owner)
    _assert_problem(bad, 400, "invalid-cursor")


# ---------------------------------------------------------------- M5 export cap race
async def test_concurrent_exports_respect_the_daily_cap(env, monkeypatch):
    monkeypatch.setattr(export_service, "MAX_EXPORTS_PER_DAY", 2)
    owner = await env.org("exp")
    url = f"/v1/organizations/{owner['X-Org-Id']}/export"
    responses = await asyncio.gather(*(env.c.post(url, headers=owner) for _ in range(6)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [202, 202, 429, 429, 429, 429], [r.text for r in responses]
