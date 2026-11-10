"""Knowledge base through the API: organisation documents + read-only global corpus."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_common.db import platform_transaction
from bomagent_common.messaging import InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_kb_indexer.handler import KbIndexer
from bomagent_testing.data import FIXTURES
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


@pytest.fixture
def env(app_engine, platform_engine):
    store = InMemoryObjectStore(enforce_tenant=False)
    queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue(), "kb": InMemoryQueue()}
    kb = make_kb()
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=store,
        queues=queues,
        kb=kb,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")
    indexer = KbIndexer(kb=kb, app_engine=app_engine, tenant_store=store)
    return client, queues, indexer


async def _org(c: httpx.AsyncClient, sub: str) -> dict[str, str]:
    tok = (await c.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    org = await c.post("/v1/organizations", headers=auth, json={"name": sub, "slug": sub})
    return auth | {"X-Org-Id": org.json()["id"]}


async def test_upload_index_list_and_isolation(env, platform_engine):
    c, queues, indexer = env
    s = uuid.uuid4().hex[:6]
    a, b = await _org(c, f"kba-{s}"), await _org(c, f"kbb-{s}")
    sheet = FIXTURES / "datasheets" / "adi-ad8232.md"
    resp = await c.post(
        "/v1/kb/documents",
        headers=a,
        data={"kind": "datasheet", "manufacturer": "Analog Devices"},
        files={"file": (sheet.name, sheet.read_bytes())},
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["status"] == "pending"
    assert doc["scope"] == "tenant"

    for item in await queues["kb"].receive(max_messages=10):
        assert await process_one(queues["kb"], item, indexer.handle)
    mine = (await c.get("/v1/kb/documents", headers=a)).json()["items"]
    assert [(d["id"], d["status"]) for d in mine] == [(doc["id"], "indexed")]
    assert mine[0]["chunks"] > 0
    assert (await c.get("/v1/kb/documents", headers=b)).json()["items"] == []

    # the global corpus is visible (read-only) to every organisation
    gid = uuid.uuid4()
    async with platform_transaction(platform_engine) as conn:
        await conn.execute(
            text(
                "INSERT INTO kb.documents (id, scope, title, mime_type, sha256, size_bytes,"
                " status, created_by) VALUES (:i, 'global', :t, 'application/pdf',"
                " repeat('c', 64), 1, 'indexed', 'platform')"
            ),
            {"i": gid, "t": f"Global {s}"},
        )
    for org in (a, b):
        glob = (await c.get("/v1/kb/documents?scope=global&limit=100", headers=org)).json()
        assert str(gid) in [d["id"] for d in glob["items"]]

    unsupported = await c.post(
        "/v1/kb/documents", headers=a, files={"file": ("tool.exe", b"MZ\x90\x00")}
    )
    assert unsupported.status_code == 415
    events = (await c.get("/v1/audit-events", headers=a)).json()["items"]
    assert "kb.document.created" in [e["action"] for e in events]
