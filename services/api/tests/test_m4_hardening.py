"""Deferred M4 review items: storage quota (L1), upload races and files in use (L2),
idempotency scope (L3), composite tenant foreign keys (L8)."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bomagent_api import idempotency, plans
from bomagent_api.app import Settings, create_app
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import InMemoryObjectStore
from bomagent_common.tenancy import tenant_scope
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore(enforce_tenant=False)


@pytest.fixture
def client(app_engine, platform_engine, store) -> httpx.AsyncClient:
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=store,
        queues={"ingest": InMemoryQueue(), "runs": InMemoryQueue()},
        kb=make_kb(),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def _owner(c: httpx.AsyncClient) -> dict[str, str]:
    s = uuid.uuid4().hex[:8]
    tok = (await c.post("/v1/dev/token", json={"sub": f"u-{s}", "email": f"u-{s}@x.eu"})).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    org = await c.post("/v1/organizations", headers=auth, json={"name": s, "slug": f"h-{s}"})
    assert org.status_code == 201, org.text
    return auth | {"X-Org-Id": org.json()["id"]}


async def _project(c: httpx.AsyncClient, owner: dict[str, str]) -> str:
    return (await c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]


async def _upload(c, owner, pid, name: str, data: bytes) -> httpx.Response:
    return await c.post(f"/v1/projects/{pid}/files", headers=owner, files={"file": (name, data)})


def test_every_plan_has_a_storage_limit():
    sizes = [plans.PLANS[n].storage_bytes for n in ("pilot", "team", "business", "enterprise")]
    assert all(s > 0 for s in sizes)
    assert sizes == sorted(sizes)


async def test_storage_quota_blocks_uploads_and_counts_replacements_once(
    client, monkeypatch, store
):
    pilot = plans.PLANS["pilot"]
    monkeypatch.setitem(
        plans.PLANS, "pilot", plans.Plan(**(pilot.__dict__ | {"storage_bytes": 10}))
    )
    owner = await _owner(client)
    pid = await _project(client, owner)
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"123456")).status_code == 201
    over = await _upload(client, owner, pid, "b.kicad_sch", b"123456")
    assert over.status_code == 429
    assert over.json()["type"].endswith("quota-exceeded")
    assert "storage" in over.json()["detail"]
    # replacing a file only counts the difference
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"123456789")).status_code == 201
    assert len(store.objects) == 1  # the rejected upload left no object behind


async def test_a_project_is_bounded_in_files_and_bytes(client, monkeypatch, store):
    from bomagent_api.routers import projects

    monkeypatch.setattr(projects, "MAX_PROJECT_FILES", 2)
    monkeypatch.setattr(projects, "MAX_PROJECT_BYTES", 30)
    owner = await _owner(client)
    pid = await _project(client, owner)
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"1" * 10)).status_code == 201
    assert (await _upload(client, owner, pid, "b.kicad_sch", b"1" * 10)).status_code == 201
    third = await _upload(client, owner, pid, "c.kicad_sch", b"1")
    assert third.status_code == 413
    assert third.json()["type"].endswith("project-too-large")
    too_big = await _upload(client, owner, pid, "a.kicad_sch", b"1" * 25)  # replace: 25 + 10
    assert too_big.status_code == 413
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"1" * 20)).status_code == 201


async def test_concurrent_uploads_of_one_name_leave_one_row_and_one_object(client, store):
    owner = await _owner(client)
    pid = await _project(client, owner)
    results = await asyncio.gather(
        *[_upload(client, owner, pid, "same.kicad_sch", bytes([i]) * 20) for i in range(4)]
    )
    assert [r.status_code for r in results] == [201] * 4
    files = (await client.get(f"/v1/projects/{pid}/files", headers=owner)).json()
    assert len(files) == 1
    assert len(store.objects) == 1


async def test_file_used_by_an_active_run_cannot_be_replaced(client, app_engine, store):
    owner = await _owner(client)
    pid = await _project(client, owner)
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"one")).status_code == 201
    org = uuid.UUID(owner["X-Org-Id"])
    async with tenant_transaction(app_engine, org) as conn:
        await conn.execute(text("UPDATE projects.files SET status = 'parsed'"))
    run = await client.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    assert run.status_code == 202
    blocked = await _upload(client, owner, pid, "a.kicad_sch", b"two")
    assert blocked.status_code == 409
    assert blocked.json()["type"].endswith("file-in-use")
    assert len(store.objects) == 1
    # a new name is still fine, and the file is free again once the run finished
    assert (await _upload(client, owner, pid, "b.kicad_sch", b"new")).status_code == 201
    async with tenant_transaction(app_engine, org) as conn:
        await conn.execute(text("UPDATE runs.runs SET status = 'failed'"))
    assert (await _upload(client, owner, pid, "a.kicad_sch", b"two")).status_code == 201


async def test_idempotency_key_is_bound_to_method_and_path(app_engine, make_tenant):
    tenant = await make_tenant()
    body = {"name": "x"}
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            await idempotency.store(
                conn, "key-12345678", body, 201, {"id": 1}, route="POST /v1/projects"
            )
        async with tenant_transaction(app_engine) as conn:
            same = await idempotency.replay(conn, "key-12345678", body, route="POST /v1/projects")
            assert same == {"id": 1}
            with pytest.raises(ProblemError) as exc:
                await idempotency.replay(conn, "key-12345678", body, route="POST /v1/runs")
            assert exc.value.problem.status == 422


async def test_tenant_scoped_foreign_keys_in_kb_and_api_keys(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    key_b, key_a, doc_b, doc_a = (uuid.uuid4() for _ in range(4))
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO tenancy.api_keys (id, tenant_id, name, prefix, key_hash, roles,"
                " created_by) VALUES (:i, :t, 'k', 'bk_abcdef', :h, ARRAY['viewer'], 'u')"
            ),
            {"i": key_b, "t": b.tenant_id, "h": "b" * 64},
        )
        await conn.execute(
            text(
                "INSERT INTO kb.documents (id, tenant_id, scope, title, mime_type, sha256,"
                " size_bytes, created_by) VALUES (:i, :t, 'tenant', 'd', 'text/plain', :h, 1, 'u')"
            ),
            {"i": doc_b, "t": b.tenant_id, "h": "b" * 64},
        )
    with pytest.raises(IntegrityError):  # replaced_by pointing at another tenant's key
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenancy.api_keys (id, tenant_id, name, prefix, key_hash,"
                    " roles, created_by, replaced_by) VALUES (:i, :t, 'k', 'ak_abcdef', :h,"
                    " ARRAY['viewer'], 'u', :r)"
                ),
                {"i": key_a, "t": a.tenant_id, "h": "a" * 64, "r": key_b},
            )
    with pytest.raises(IntegrityError):  # supersedes pointing at another tenant's document
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb.documents (id, tenant_id, scope, title, mime_type, sha256,"
                    " size_bytes, created_by, supersedes) VALUES (:i, :t, 'tenant', 'd',"
                    " 'text/plain', :h, 1, 'u', :s)"
                ),
                {"i": doc_a, "t": a.tenant_id, "h": "a" * 64, "s": doc_b},
            )
