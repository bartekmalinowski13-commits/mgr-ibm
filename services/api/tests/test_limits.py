"""Plan limits, rate limiting and usage metering."""

from __future__ import annotations

import uuid

import httpx
import pytest

from bomagent_api import plans
from bomagent_api.app import Settings, create_app
from bomagent_common.messaging import InMemoryQueue
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.api import mark_files_parsed
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


@pytest.fixture
def client(app_engine, platform_engine) -> httpx.AsyncClient:
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={"ingest": InMemoryQueue(), "runs": InMemoryQueue()},
        kb=make_kb(),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def _login(c: httpx.AsyncClient, sub: str) -> dict[str, str]:
    tok = (await c.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


async def _org(c: httpx.AsyncClient, auth: dict[str, str], slug: str) -> dict[str, str]:
    org = await c.post("/v1/organizations", headers=auth, json={"name": slug, "slug": slug})
    assert org.status_code == 201, org.text
    return auth | {"X-Org-Id": org.json()["id"]}


def _tight(monkeypatch, **limits: float) -> None:
    pilot = plans.PLANS["pilot"]
    monkeypatch.setitem(plans.PLANS, "pilot", plans.Plan(**(pilot.__dict__ | limits)))


async def test_rate_limit_per_subject(client, monkeypatch):
    _tight(monkeypatch, requests_per_minute=3)
    s = uuid.uuid4().hex[:6]
    alice = await _org(client, await _login(client, f"a-{s}"), f"rl-{s}")
    codes = [(await client.get("/v1/projects", headers=alice)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    limited = await client.get("/v1/projects", headers=alice)
    assert limited.json()["type"].endswith("rate-limited")
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    # another organisation (and subject) has its own window
    bob = await _org(client, await _login(client, f"b-{s}"), f"rl2-{s}")
    assert (await client.get("/v1/projects", headers=bob)).status_code == 200


async def test_project_run_and_org_quotas_and_usage(client, monkeypatch, app_engine):
    _tight(monkeypatch, max_projects=1, max_concurrent_runs=1)
    s = uuid.uuid4().hex[:6]
    auth = await _login(client, f"q-{s}")
    owner = await _org(client, auth, f"q-{s}")
    pid = (await client.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    second = await client.post("/v1/projects", headers=owner, json={"name": "p2"})
    assert second.status_code == 429
    assert second.json()["type"].endswith("quota-exceeded")

    upload = await client.post(
        f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.kicad_sch", b"12345")}
    )
    assert upload.status_code == 201
    await mark_files_parsed(app_engine, owner["X-Org-Id"])
    run = await client.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    assert run.status_code == 202
    again = await client.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    assert again.status_code == 429  # one run is still queued

    report = (await client.get("/v1/usage", headers=owner)).json()
    assert report["usage"]["files_uploaded"] == 1
    assert report["usage"]["bytes_uploaded"] == 5
    assert report["limits"]["max_projects"] == 1
    assert report["plan"] == "pilot"

    for n in range(2):
        await _org(client, auth, f"q{n}-{s}")
    fourth = await client.post(
        "/v1/organizations", headers=auth, json={"name": "x", "slug": f"q9-{s}"}
    )
    assert fourth.status_code == 429


async def test_monthly_llm_budget_blocks_new_runs(client, monkeypatch, app_engine):
    from bomagent_common.db import tenant_transaction
    from bomagent_common.metering import record_usage

    s = uuid.uuid4().hex[:6]
    owner = await _org(client, await _login(client, f"m-{s}"), f"m-{s}")
    pid = (await client.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    await client.post(
        f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.kicad_sch", b"x")}
    )
    async with tenant_transaction(app_engine, uuid.UUID(owner["X-Org-Id"])) as conn:
        await record_usage(conn, cost_eur=plans.PLANS["pilot"].llm_budget_eur_per_month)
    await mark_files_parsed(app_engine, owner["X-Org-Id"])
    blocked = await client.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    assert blocked.status_code == 429
    assert "budget" in blocked.json()["detail"]
    with pytest.raises(ValueError, match="unknown"):
        async with tenant_transaction(app_engine, uuid.UUID(owner["X-Org-Id"])) as conn:
            await record_usage(conn, gpu_hours=1)
