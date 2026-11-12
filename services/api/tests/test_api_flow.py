"""End-to-end through the API (local mock IdP, in-memory S3/SQS, real PostgreSQL)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from bomagent_agent_worker.handler import RunWorker
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_api.app import Settings, create_app
from bomagent_common.db import platform_transaction
from bomagent_common.messaging import InMemoryQueue, process_one
from bomagent_common.storage import InMemoryObjectStore
from bomagent_ingest.handler import IngestWorker
from bomagent_llm.chat import FakeChat
from bomagent_testing.api import mark_files_parsed
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine) -> None:
        self.store = InMemoryObjectStore(enforce_tenant=False)
        self.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
        self.kb = make_kb()
        self.app = create_app(
            Settings(environment="test", auth_mode="local", sse_interval_s=0.01, sse_timeout_s=5),
            engine=app_engine,
            platform_engine=platform_engine,
            store=self.store,
            queues=self.queues,
            kb=self.kb,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://api"
        )
        self.engine = app_engine

    async def login(self, sub: str) -> dict[str, str]:
        resp = await self.client.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def org(self, auth: dict[str, str], slug: str) -> dict[str, str]:
        resp = await self.client.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert resp.status_code == 201, resp.text
        return auth | {"X-Org-Id": resp.json()["id"]}

    async def drain(self, name: str, handler) -> None:
        queue = self.queues[name]
        for item in await queue.receive(max_messages=50):
            assert await process_one(queue, item, handler)


@pytest.fixture
async def env(app_engine, platform_engine):
    return Env(app_engine, platform_engine)


async def test_full_flow_and_tenant_boundaries(env):
    s = uuid.uuid4().hex[:6]
    alice = await env.org(await env.login(f"alice-{s}"), f"acme-{s}")
    bob = await env.org(await env.login(f"bob-{s}"), f"globex-{s}")
    c = env.client

    me = (await c.get("/v1/me", headers=alice)).json()
    assert [o["slug"] for o in me["organizations"]] == [f"acme-{s}"]

    # project with idempotency
    body = {"name": "ECG front end"}
    first = await c.post("/v1/projects", headers=alice | {"Idempotency-Key": f"k-{s}-1"}, json=body)
    again = await c.post("/v1/projects", headers=alice | {"Idempotency-Key": f"k-{s}-1"}, json=body)
    assert first.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    clash = await c.post(
        "/v1/projects", headers=alice | {"Idempotency-Key": f"k-{s}-1"}, json={"name": "other"}
    )
    assert clash.status_code == 422
    pid = first.json()["id"]

    # upload the KiCad project and parse it in the (sandboxed) ingest worker
    for path in sorted((KICAD_FIXTURES / "ecg-frontend").glob("*.kicad_*")):
        resp = await c.post(
            f"/v1/projects/{pid}/files",
            headers=alice,
            files={"file": (path.name, path.read_bytes())},
        )
        assert resp.status_code == 201, resp.text
    await env.drain("ingest", IngestWorker(env.engine, env.store).handle)
    files = (await c.get(f"/v1/projects/{pid}/files", headers=alice)).json()
    assert {f["status"] for f in files} == {"parsed"}
    assert files[0]["summary"]["components"] == 30

    # run variant B; the agent worker processes it
    run = await c.post("/v1/runs", headers=alice, json={"project_id": pid, "variant": "B"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    assert run.json()["status"] == "queued"
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    worker = RunWorker(
        engine=env.engine,
        store=env.store,
        chat=FakeChat(heuristic_responder),
        kb=env.kb,
        retriever_factory=lambda t, snap: retriever,
    )
    await env.drain("runs", worker.handle)
    done = (await c.get(f"/v1/runs/{run_id}", headers=alice)).json()
    assert done["status"] == "completed"
    assert done["usage"]["llm_calls"] > 0

    events = await c.get(f"/v1/runs/{run_id}/events", headers=alice)
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: end" in events.text
    assert '"status": "completed"' in events.text
    # progress names the last finished step (live step display)
    assert '"step": "' in events.text

    bom = (await c.get(f"/v1/runs/{run_id}/bom", headers=alice)).json()
    assert bom["version"] == 1
    line = next(i for i in bom["bom"]["items"] if "R5" in i["refdes"])

    # correction -> new version, user provenance, tenant knowledge
    patched = await c.patch(
        f"/v1/runs/{run_id}/bom/items/{line['line']}",
        headers=alice,
        json={"mpn": "ERJ-3EKF1003V", "manufacturer": "Panasonic", "reason": "preferred supplier"},
    )
    assert patched.status_code == 200, patched.text
    new_line = next(i for i in patched.json()["bom"]["items"] if "R5" in i["refdes"])
    assert patched.json()["version"] == 2
    assert new_line["provenance"]["mpn"]["kind"] == "user"
    async with env.engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": alice["X-Org-Id"]}
        )
        assert "ERJ-3EKF1003V" in await env.kb.known_mpns(conn)

    csv = await c.get(f"/v1/runs/{run_id}/bom.csv", headers=alice)
    assert csv.status_code == 200
    assert "ERJ-3EKF1003V" in csv.text

    audit = (await c.get("/v1/audit-events", headers=alice)).json()
    actions = [e["action"] for e in audit["items"]]
    for expected in (
        "org.created",
        "project.created",
        "file.uploaded",
        "run.created",
        "run.completed",
        "bom.item_updated",
        "bom.exported",
    ):
        assert expected in actions
    assert (await c.get("/v1/audit-events/verify", headers=alice)).json()["ok"] is True

    # ---- tenant boundaries
    spoof = await c.get(f"/v1/projects/{pid}", headers=bob | {"X-Org-Id": alice["X-Org-Id"]})
    assert spoof.status_code == 403
    for url in (f"/v1/projects/{pid}", f"/v1/runs/{run_id}", f"/v1/runs/{run_id}/bom"):
        assert (await c.get(url, headers=bob)).status_code == 404
    assert (await c.get("/v1/projects", headers=bob)).json()["items"] == []
    assert (
        await c.post("/v1/runs", headers=bob, json={"project_id": pid, "variant": "A"})
    ).status_code == 404


async def test_auth_errors_and_roles(env, platform_engine):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"org-{s}")
    c = env.client
    assert (await c.get("/v1/me")).status_code == 401
    bad = await c.get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert bad.headers["content-type"].startswith("application/problem+json")
    assert (
        await c.get("/v1/projects", headers={k: v for k, v in owner.items() if k != "X-Org-Id"})
    ).status_code == 400
    assert (await c.get("/v1/projects", headers=owner | {"X-Org-Id": "x"})).status_code == 400
    dup = await c.post("/v1/organizations", headers=owner, json={"name": "a", "slug": f"org-{s}"})
    assert dup.status_code == 409

    viewer_sub = f"view-{s}"
    async with platform_transaction(platform_engine) as conn:
        await conn.execute(
            text(
                "INSERT INTO tenancy.memberships (tenant_id, user_sub, email,"
                " roles) VALUES (:t, :s, 'v@x.eu', ARRAY['viewer'])"
            ),
            {"t": owner["X-Org-Id"], "s": viewer_sub},
        )
    viewer = await env.login(viewer_sub) | {"X-Org-Id": owner["X-Org-Id"]}
    assert (await c.get("/v1/projects", headers=viewer)).status_code == 200
    assert (await c.post("/v1/projects", headers=viewer, json={"name": "x"})).status_code == 403
    assert (await c.get("/v1/audit-events", headers=viewer)).status_code == 403

    pid = (await c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    assert (
        await c.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    ).status_code == 409  # no files yet
    wrong = await c.post(
        "/v1/runs",
        headers=owner,
        json={"project_id": pid, "variant": "B", "runtime": "langgraph_a"},
    )
    assert wrong.status_code == 422
    unverified = await c.post(
        "/v1/runs",
        headers=owner,
        json={"project_id": pid, "variant": "B", "model_id": "claude-sonnet-eu"},
    )
    assert unverified.status_code == 422
    assert unverified.json()["type"].endswith("model-not-allowed")

    # pagination
    for n in range(3):
        await c.post("/v1/projects", headers=owner, json={"name": f"p{n}"})
    page1 = (await c.get("/v1/projects?limit=2", headers=owner)).json()
    page2 = (
        await c.get(f"/v1/projects?limit=2&cursor={page1['next_cursor']}", headers=owner)
    ).json()
    assert len(page1["items"]) == 2
    assert {p["id"] for p in page1["items"]}.isdisjoint({p["id"] for p in page2["items"]})
    assert (await c.get("/v1/projects?cursor=@@", headers=owner)).status_code == 400

    resp = await c.get("/healthz")
    assert resp.headers["x-frame-options"] == "DENY"


def test_local_idp_refused_outside_local_and_openapi_is_current():
    with pytest.raises(RuntimeError, match="local/test"):
        create_app(Settings(environment="prod", auth_mode="local"))
    from pathlib import Path

    from bomagent_api.app import openapi_document

    committed = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    assert committed == json.loads(json.dumps(openapi_document(), sort_keys=True))


async def test_concurrent_idempotent_posts_and_bom_edits(env):
    """Races must not end in 500: same-key POSTs replay, parallel edits get versions."""
    import asyncio

    s = uuid.uuid4().hex[:6]
    alice = await env.org(await env.login(f"alice-{s}"), f"race-{s}")
    c = env.client
    key = alice | {"Idempotency-Key": f"race-{s}-key"}
    created = await asyncio.gather(
        *(c.post("/v1/projects", headers=key, json={"name": "same"}) for _ in range(5))
    )
    assert {r.status_code for r in created} == {201}
    assert len({r.json()["id"] for r in created}) == 1
    # the same key from another member is that member's own key
    bob = await env.login(f"bob-{s}")
    async with platform_transaction(env.app.state.platform_engine) as conn:
        await conn.execute(
            text(
                "INSERT INTO tenancy.memberships (tenant_id, user_sub, email, roles)"
                " VALUES (:t, :s, 'b@x.eu', ARRAY['engineer'])"
            ),
            {"t": alice["X-Org-Id"], "s": f"bob-{s}"},
        )
    other = await c.post(
        "/v1/projects",
        headers=bob | {"X-Org-Id": alice["X-Org-Id"], "Idempotency-Key": f"race-{s}-key"},
        json={"name": "same"},
    )
    assert other.status_code == 201
    assert other.json()["id"] != created[0].json()["id"]

    pid = created[0].json()["id"]
    for path in sorted((KICAD_FIXTURES / "ecg-frontend").glob("*.kicad_*")):
        await c.post(
            f"/v1/projects/{pid}/files",
            headers=alice,
            files={"file": (path.name, path.read_bytes())},
        )
    await mark_files_parsed(env.engine, alice["X-Org-Id"])
    run_id = (
        await c.post("/v1/runs", headers=alice, json={"project_id": pid, "variant": "B"})
    ).json()["id"]
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    worker = RunWorker(
        engine=env.engine,
        store=env.store,
        chat=FakeChat(heuristic_responder),
        kb=env.kb,
        retriever_factory=lambda t, snap: retriever,
    )
    await env.drain("runs", worker.handle)
    edits = await asyncio.gather(
        *(
            c.patch(
                f"/v1/runs/{run_id}/bom/items/1",
                headers=alice,
                json={"manufacturer": f"M{n}", "reason": "race"},
            )
            for n in range(5)
        )
    )
    assert {r.status_code for r in edits} == {200}, [r.text for r in edits]
    assert sorted(r.json()["version"] for r in edits) == [2, 3, 4, 5, 6]


async def test_evaluation_against_a_reference_bom(env):
    s = uuid.uuid4().hex[:6]
    alice = await env.org(await env.login(f"alice-{s}"), f"ev-{s}")
    bob = await env.org(await env.login(f"bob-{s}"), f"ev2-{s}")
    c = env.client
    pid = (await c.post("/v1/projects", headers=alice, json={"name": "ecg"})).json()["id"]
    fixture = KICAD_FIXTURES / "ecg-frontend"
    for path in sorted(fixture.glob("*.kicad_*")):
        await c.post(
            f"/v1/projects/{pid}/files",
            headers=alice,
            files={"file": (path.name, path.read_bytes())},
        )
    await env.drain("ingest", IngestWorker(env.engine, env.store).handle)
    run_id = (
        await c.post("/v1/runs", headers=alice, json={"project_id": pid, "variant": "B"})
    ).json()["id"]
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    worker = RunWorker(
        engine=env.engine,
        store=env.store,
        chat=FakeChat(heuristic_responder),
        kb=env.kb,
        retriever_factory=lambda t, snap: retriever,
    )
    await env.drain("runs", worker.handle)

    trace = await c.get(f"/v1/runs/{run_id}/trace", headers=alice)
    assert trace.status_code == 200, trace.text
    steps = trace.json()
    assert steps
    assert {"node", "duration_s", "llm_calls"} == set(steps[0])
    assert sum(st["llm_calls"] for st in steps) > 0
    assert (await c.get(f"/v1/runs/{run_id}/trace", headers=bob)).status_code == 404
    reference = (fixture / "reference_bom.csv").read_bytes()
    url = f"/v1/runs/{run_id}/evaluation"
    resp = await c.post(url, headers=alice, files={"reference": ("ref.csv", reference)})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["summary"]["line_f1"] > 0.8
    assert report["lines"]["tp"] > 0
    assert set(report["fields"]) >= {"mpn", "value"}
    assert all({"refdes", "field", "predicted", "expected"} <= set(d) for d in report["diffs"])

    for junk in (b"just,some\nnoise", b"\r0", b"\xff\xfe", b'a,"b\rc'):
        bad = await c.post(url, headers=alice, files={"reference": ("ref.csv", junk)})
        assert bad.status_code == 422, (junk, bad.text)
    huge = await c.post(
        url, headers=alice, files={"reference": ("ref.csv", b"a" * (1024 * 1024 + 1))}
    )
    assert huge.status_code == 413
    other = await c.post(url, headers=bob, files={"reference": ("ref.csv", reference)})
    assert other.status_code == 404
    events = (await c.get("/v1/audit-events", headers=alice)).json()["items"]
    assert "bom.evaluated" in [e["action"] for e in events]
