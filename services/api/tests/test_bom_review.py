"""A person reviews a run's BOM: edits keep the agents' output intact, carry ``user``
provenance, re-run the rule pack, are audited, and can become the organisation's knowledge."""

from __future__ import annotations

import pytest

from .test_api_flow import _parsed_design

pytestmark = pytest.mark.integration


async def _completed_run(stack, ctx) -> str:
    design_id = await _parsed_design(stack, ctx)
    run = await stack.client.post(
        "/v1/runs",
        json={"design_id": design_id, "variant": "B", "model_id": "fake-closed"},
        headers=stack.token(ctx) | {"Idempotency-Key": f"review-{design_id}"},
    )
    await stack.drain()
    return run.json()["id"]


async def test_edit_creates_reviewed_copy_with_user_provenance(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    run_id = await _completed_run(stack, ctx)
    original = (await stack.client.get(f"/v1/runs/{run_id}/bom", headers=h)).json()
    line = original["items"][0]

    res = await stack.client.patch(
        f"/v1/runs/{run_id}/bom/items/{line['line']}",
        json={"mpn": "GRM188R71H104KA93D", "manufacturer": "Murata", "note": "approved part"},
        headers=h,
    )
    assert res.status_code == 200, res.text
    edited = next(i for i in res.json()["items"] if i["line"] == line["line"])
    assert edited["mpn"] == "GRM188R71H104KA93D"
    assert edited["provenance"]["mpn"]["kind"] == "user"
    assert edited["provenance"]["mpn"]["user_id"] == ctx.actor_id
    assert edited["provenance"]["mpn"]["rationale"] == "approved part"

    latest = (await stack.client.get(f"/v1/runs/{run_id}/bom", headers=h)).json()
    kept = (await stack.client.get(f"/v1/runs/{run_id}/bom?version=original", headers=h)).json()
    assert (
        next(i for i in latest["items"] if i["line"] == line["line"])["mpn"] == "GRM188R71H104KA93D"
    )
    assert kept == original  # the experiment's output is never modified

    run = (await stack.client.get(f"/v1/runs/{run_id}", headers=h)).json()
    assert run["review_edits"] == 1
    assert run["reviewed_at"]
    audit = (await stack.client.get("/v1/audit/events", headers=h)).json()["items"]
    edit = next(e for e in audit if e["action"] == "bom.item.edit")
    assert edit["object_id"] == run_id

    # a second edit builds on the reviewed copy
    again = await stack.client.patch(
        f"/v1/runs/{run_id}/bom/items/{line['line']}",
        json={"dnp": True, "note": "not fitted"},
        headers=h,
    )
    second = next(i for i in again.json()["items"] if i["line"] == line["line"])
    assert second["dnp"] is True
    assert second["mpn"] == "GRM188R71H104KA93D"


async def test_remembered_correction_becomes_organisation_knowledge(stack, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    run_id = await _completed_run(stack, a)
    res = await stack.client.patch(
        f"/v1/runs/{run_id}/bom/items/1",
        json={
            "mpn": "TEST-MPN-0001",
            "manufacturer": "Acme",
            "note": "our stock",
            "remember": True,
        },
        headers=stack.token(a),
    )
    assert res.status_code == 200, res.text
    await stack.drain()
    docs_a = (
        await stack.client.get("/v1/kb/documents?scope=tenant", headers=stack.token(a))
    ).json()
    assert [d["kind"] for d in docs_a["items"]] == ["correction"]
    docs_b = (
        await stack.client.get("/v1/kb/documents?scope=tenant", headers=stack.token(b))
    ).json()
    assert docs_b["items"] == []  # never learned by another organisation


async def test_review_validation_and_roles(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    run_id = await _completed_run(stack, ctx)
    url = f"/v1/runs/{run_id}/bom/items/1"
    assert (await stack.client.patch(url, json={"note": "x"}, headers=h)).status_code == 422
    assert (await stack.client.patch(url, json={"mpn": "A1"}, headers=h)).status_code == 422
    assert (
        await stack.client.patch(url, json={"mpn": "<script>", "note": "x"}, headers=h)
    ).status_code == 422
    missing = f"/v1/runs/{run_id}/bom/items/999"
    assert (
        await stack.client.patch(missing, json={"dnp": True, "note": "x"}, headers=h)
    ).status_code == 404
    viewer = stack.token(ctx, roles=("viewer",))
    assert (
        await stack.client.patch(url, json={"dnp": True, "note": "x"}, headers=viewer)
    ).status_code == 403


@pytest.mark.isolation
async def test_other_tenant_cannot_edit_or_read_review(stack, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    run_id = await _completed_run(stack, a)
    res = await stack.client.patch(
        f"/v1/runs/{run_id}/bom/items/1", json={"dnp": True, "note": "x"}, headers=stack.token(b)
    )
    assert res.status_code == 404
