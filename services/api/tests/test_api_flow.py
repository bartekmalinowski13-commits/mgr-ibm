"""End-to-end flow through the API with real Postgres/RLS and the workers in-process:
project -> design upload -> parse -> run (idempotent) -> BOM, trace, SSE, audit chain.
Plus authorisation and cross-tenant isolation (marker ``isolation`` - blocks merges)."""

from __future__ import annotations

import json
import uuid

import pytest

from bomagent_common.audit import verify_chain
from bomagent_common.db import tenant_transaction
from bomagent_common.storage import tenant_key
from bomagent_common.tenancy import tenant_scope

from .conftest import ROOT

pytestmark = pytest.mark.integration
PULSE = ROOT / "kicad" / "pulse-ox"


async def _parsed_design(stack, ctx) -> str:
    h = stack.token(ctx)
    project = (
        await stack.client.post("/v1/projects", json={"name": "Pulse oximeter"}, headers=h)
    ).json()
    files = sorted(p.name for p in PULSE.iterdir() if p.suffix == ".kicad_sch")
    created = await stack.client.post(
        f"/v1/projects/{project['id']}/designs", json={"filenames": files}, headers=h
    )
    assert created.status_code == 201, created.text
    design = created.json()
    assert [u["filename"] for u in design["uploads"]] == files
    with tenant_scope(ctx):  # the browser PUTs to the presigned URLs
        for f in files:
            await stack.store.put(
                tenant_key(ctx.tenant_id, "designs", design["id"], "files", f),
                (PULSE / f).read_bytes(),
            )
    done = await stack.client.post(f"/v1/designs/{design['id']}/complete", headers=h)
    assert done.status_code == 202
    assert done.json()["status"] == "uploaded"
    assert (
        await stack.client.post(f"/v1/designs/{design['id']}/complete", headers=h)
    ).status_code == 409
    await stack.drain()
    listed = (await stack.client.get(f"/v1/projects/{project['id']}/designs", headers=h)).json()
    assert [d["id"] for d in listed["items"]] == [design["id"]]
    parsed = (await stack.client.get(f"/v1/designs/{design['id']}", headers=h)).json()
    assert parsed["status"] == "parsed"
    assert parsed["components"] == 11
    assert parsed["source_format"].startswith("kicad")
    return design["id"]


async def test_full_flow_from_upload_to_bom_with_audit_chain(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    design_id = await _parsed_design(stack, ctx)

    body = {
        "design_id": design_id,
        "variant": "B",
        "model_id": "fake-closed",
        "requirements": {"applied_part": "BF"},
    }
    first = await stack.client.post(
        "/v1/runs", json=body, headers=h | {"Idempotency-Key": "run-key-0001"}
    )
    assert first.status_code == 202, first.text
    again = await stack.client.post(
        "/v1/runs", json=body, headers=h | {"Idempotency-Key": "run-key-0001"}
    )
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert len(stack.runs) == 1
    run_id = first.json()["id"]
    assert (await stack.client.get(f"/v1/runs/{run_id}/bom", headers=h)).status_code == 409

    await stack.drain()
    run = (await stack.client.get(f"/v1/runs/{run_id}", headers=h)).json()
    assert run["status"] == "completed"
    assert run["usage"]["llm_calls"] >= 1
    bom = (await stack.client.get(f"/v1/runs/{run_id}/bom", headers=h)).json()
    assert bom["variant"] == "B:fake-closed"
    assert len(bom["items"]) == 9
    assert bom["rule_pack"] == "core"
    assert isinstance(bom["findings"], list)
    trace = (await stack.client.get(f"/v1/runs/{run_id}/trace", headers=h)).json()
    assert next(s["step"] for s in trace["trace"]) == "group"

    events = await stack.client.get(f"/v1/runs/{run_id}/events", headers=h)
    assert events.headers["content-type"].startswith("text/event-stream")
    payloads = [
        json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")
    ]
    assert payloads[-1]["status"] == "completed"

    listing = (await stack.client.get("/v1/runs?limit=1", headers=h)).json()
    assert listing["items"][0]["id"] == run_id

    audit = (await stack.client.get("/v1/audit/events", headers=h)).json()["items"]
    actions = [e["action"] for e in reversed(audit)]
    assert actions == [
        "project.create",
        "design.create",
        "design.upload_complete",
        "design.parse",
        "run.create",
        "run.completed",
    ]
    assert audit[0]["actor_type"] == "service"
    async with tenant_transaction(stack.services.engine, ctx.tenant_id) as conn:
        assert (await verify_chain(conn, ctx.tenant_id)).ok


async def test_validation_errors(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    project = (await stack.client.post("/v1/projects", json={"name": "P"}, headers=h)).json()
    bad_name = await stack.client.post(
        f"/v1/projects/{project['id']}/designs", json={"filenames": ["../etc/passwd"]}, headers=h
    )
    assert bad_name.status_code == 422
    dup = await stack.client.post(
        f"/v1/projects/{project['id']}/designs",
        json={"filenames": ["a.kicad_sch", "a.kicad_sch"]},
        headers=h,
    )
    assert dup.status_code == 422
    design = (
        await stack.client.post(
            f"/v1/projects/{project['id']}/designs", json={"filenames": ["a.kicad_sch"]}, headers=h
        )
    ).json()
    body = {"design_id": design["id"], "variant": "A", "model_id": "fake-closed"}
    not_parsed = await stack.client.post(
        "/v1/runs", json=body, headers=h | {"Idempotency-Key": "k-not-parsed"}
    )
    assert not_parsed.status_code == 409
    assert not_parsed.headers["content-type"].startswith("application/problem+json")
    unverified = await stack.client.post(
        "/v1/runs",
        json=body | {"model_id": "claude-opus-eu"},
        headers=h | {"Idempotency-Key": "k-unverified"},
    )
    assert unverified.status_code == 422
    assert "unverified" in unverified.json()["detail"]
    no_key = await stack.client.post("/v1/runs", json=body, headers=h)
    assert no_key.status_code == 422
    assert (await stack.client.get("/v1/projects?cursor=@@@", headers=h)).status_code == 400


async def test_failed_parse_is_reported(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    project = (await stack.client.post("/v1/projects", json={"name": "P"}, headers=h)).json()
    design = (
        await stack.client.post(
            f"/v1/projects/{project['id']}/designs", json={"filenames": ["board.brd"]}, headers=h
        )
    ).json()
    with tenant_scope(ctx):
        await stack.store.put(
            tenant_key(ctx.tenant_id, "designs", design["id"], "files", "board.brd"),
            b"\x00binary allegro",
        )
    await stack.client.post(f"/v1/designs/{design['id']}/complete", headers=h)
    await stack.drain()
    got = (await stack.client.get(f"/v1/designs/{design['id']}", headers=h)).json()
    assert got["status"] == "failed"
    assert got["error"]


async def test_authentication_and_roles(stack, make_tenant):
    ctx = await make_tenant()
    assert (await stack.client.get("/v1/projects")).status_code == 401
    assert (
        await stack.client.get("/v1/projects", headers={"Authorization": "Bearer nope"})
    ).status_code == 401
    viewer = stack.token(ctx, roles=("viewer",))
    assert (await stack.client.get("/v1/projects", headers=viewer)).status_code == 200
    assert (
        await stack.client.post("/v1/projects", json={"name": "x"}, headers=viewer)
    ).status_code == 403
    assert (await stack.client.get("/v1/audit/events", headers=viewer)).status_code == 403
    nobody = stack.token(ctx, roles=("superuser",))
    assert (await stack.client.get("/v1/projects", headers=nobody)).status_code == 403


@pytest.mark.isolation
async def test_tenants_cannot_see_each_others_projects_designs_runs(stack, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    design_id = await _parsed_design(stack, a)
    ha, hb = stack.token(a), stack.token(b)
    run = await stack.client.post(
        "/v1/runs",
        json={"design_id": design_id, "variant": "B", "model_id": "fake-closed"},
        headers=ha | {"Idempotency-Key": "iso-run-0001"},
    )
    await stack.drain()
    run_id = run.json()["id"]
    assert (await stack.client.get(f"/v1/designs/{design_id}", headers=hb)).status_code == 404
    projects_a = (await stack.client.get("/v1/projects", headers=ha)).json()["items"]
    foreign = await stack.client.get(f"/v1/projects/{projects_a[0]['id']}/designs", headers=hb)
    assert foreign.status_code == 404
    assert (await stack.client.get(f"/v1/runs/{run_id}", headers=hb)).status_code == 404
    assert (await stack.client.get(f"/v1/runs/{run_id}/bom", headers=hb)).status_code == 404
    assert (await stack.client.get("/v1/projects", headers=hb)).json()["items"] == []
    assert (await stack.client.get("/v1/runs", headers=hb)).json()["items"] == []
    # B cannot start a run on A's design, even with A's design id
    stolen = await stack.client.post(
        "/v1/runs",
        json={"design_id": design_id, "variant": "B", "model_id": "fake-closed"},
        headers=hb | {"Idempotency-Key": "iso-run-0002"},
    )
    assert stolen.status_code == 404
    # the same idempotency key in another tenant is a different run
    other = (await stack.client.post("/v1/projects", json={"name": "B"}, headers=hb)).json()
    assert other["id"] != design_id
    audit_b = (await stack.client.get("/v1/audit/events", headers=hb)).json()["items"]
    assert [e["action"] for e in audit_b] == ["project.create"]
    assert uuid.UUID(run_id)


async def test_cursor_pagination_is_stable(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    names = [f"P{i}" for i in range(5)]
    for n in names:
        assert (
            await stack.client.post("/v1/projects", json={"name": n}, headers=h)
        ).status_code == 201
    seen, cursor = [], None
    while True:
        url = "/v1/projects?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = (await stack.client.get(url, headers=h)).json()
        seen += [p["name"] for p in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(reversed(names))
    audit_page = (await stack.client.get("/v1/audit/events?limit=2", headers=h)).json()
    assert audit_page["next_cursor"] is not None
    older = (
        await stack.client.get(
            f"/v1/audit/events?limit=2&before_seq={audit_page['next_cursor']}", headers=h
        )
    ).json()
    assert older["items"][0]["seq"] < audit_page["items"][-1]["seq"]
