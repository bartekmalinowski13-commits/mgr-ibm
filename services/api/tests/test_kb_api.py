"""Knowledge-base API: register -> presigned upload -> index (kb-indexer in-process) -> list.
Plus deduplication, validation, roles and cross-tenant isolation (marker ``isolation``)."""

from __future__ import annotations

import hashlib

import pytest

from bomagent_common.audit import verify_chain
from bomagent_common.db import tenant_transaction
from bomagent_common.tenancy import tenant_scope

from .conftest import ROOT

pytestmark = pytest.mark.integration
DATASHEET = ROOT / "datasheets" / "adi-ad8232.md"
INJECTION = ROOT / "datasheets" / "malicious-injection.md"


def _body(path, **extra) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "filename": path.name,
        "title": path.stem,
        "kind": "datasheet",
        "manufacturer": "Analog Devices",
        "mime_type": "text/markdown",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    } | extra


async def _upload(stack, ctx, path) -> dict[str, object]:
    h = stack.token(ctx)
    created = await stack.client.post("/v1/kb/documents", json=_body(path), headers=h)
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["status"] == "pending"
    assert doc["scope"] == "tenant"
    url = doc["upload"]["url"]
    assert url.startswith(f"memory://put/tenants/{ctx.tenant_id}/kb/{doc['id']}/")
    with tenant_scope(ctx):  # the browser PUT to S3, under the tenant prefix
        await stack.store.put(url.removeprefix("memory://put/").split("?")[0], path.read_bytes())
    done = await stack.client.post(f"/v1/kb/documents/{doc['id']}/complete", headers=h)
    assert done.status_code == 202, done.text
    await stack.drain()
    return doc


async def test_document_is_registered_uploaded_indexed_and_listed(stack, make_tenant, app_engine):
    ctx = await make_tenant()
    h = stack.token(ctx)
    doc = await _upload(stack, ctx, DATASHEET)

    got = (await stack.client.get(f"/v1/kb/documents/{doc['id']}", headers=h)).json()
    assert got["status"] == "indexed"
    assert got["indexed_at"]
    listed = (await stack.client.get("/v1/kb/documents?scope=tenant", headers=h)).json()
    assert [d["id"] for d in listed["items"]] == [doc["id"]]

    # same content again: no second copy, no upload target
    again = await stack.client.post("/v1/kb/documents", json=_body(DATASHEET), headers=h)
    assert again.status_code == 200
    assert again.json()["id"] == doc["id"]
    assert again.json()["upload"] is None
    # already indexed: completing again is a conflict
    second = await stack.client.post(f"/v1/kb/documents/{doc['id']}/complete", headers=h)
    assert second.status_code == 409

    actions = [
        e["action"] for e in (await stack.client.get("/v1/audit/events", headers=h)).json()["items"]
    ]
    assert {"kb.document.created", "kb.document.upload_complete"} <= set(actions)
    async with tenant_transaction(app_engine, ctx.tenant_id) as conn:
        assert await verify_chain(conn, ctx.tenant_id)


async def test_injected_document_is_indexed_with_suspicious_chunks_flagged(stack, make_tenant):
    ctx = await make_tenant()
    doc = await _upload(stack, ctx, INJECTION)
    got = (await stack.client.get(f"/v1/kb/documents/{doc['id']}", headers=stack.token(ctx))).json()
    # indexed, but retrieval drops chunks flagged as injection (covered in the kb package tests)
    assert got["status"] == "indexed"


async def test_validation_and_roles(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    bad = [
        _body(DATASHEET, sha256="xyz"),
        _body(DATASHEET, filename="../etc/passwd"),
        _body(DATASHEET, size_bytes=60 * 1024 * 1024),
        _body(DATASHEET, mime_type="application/x-msdownload"),
        _body(DATASHEET, unexpected=True),
    ]
    for body in bad:
        assert (
            await stack.client.post("/v1/kb/documents", json=body, headers=h)
        ).status_code == 422
    viewer = stack.token(ctx, roles=("viewer",))
    assert (
        await stack.client.post("/v1/kb/documents", json=_body(DATASHEET), headers=viewer)
    ).status_code == 403
    assert (await stack.client.get("/v1/kb/documents", headers=viewer)).status_code == 200
    assert (
        await stack.client.get("/v1/kb/documents?cursor=not-a-cursor", headers=h)
    ).status_code == 400


async def test_complete_without_indexing_configured_is_503(stack, make_tenant):
    ctx = await make_tenant()
    h = stack.token(ctx)
    doc = (await stack.client.post("/v1/kb/documents", json=_body(DATASHEET), headers=h)).json()
    stack.services.kb_queue = None
    res = await stack.client.post(f"/v1/kb/documents/{doc['id']}/complete", headers=h)
    assert res.status_code == 503


@pytest.mark.isolation
async def test_tenants_cannot_see_each_others_documents(stack, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    doc = await _upload(stack, a, DATASHEET)
    hb = stack.token(b)
    assert (await stack.client.get(f"/v1/kb/documents/{doc['id']}", headers=hb)).status_code == 404
    assert (
        await stack.client.post(f"/v1/kb/documents/{doc['id']}/complete", headers=hb)
    ).status_code == 404
    assert (await stack.client.get("/v1/kb/documents?scope=tenant", headers=hb)).json()[
        "items"
    ] == []
    # the same file in another organisation is that organisation's own copy
    own = await stack.client.post("/v1/kb/documents", json=_body(DATASHEET), headers=hb)
    assert own.status_code == 201
    assert own.json()["id"] != doc["id"]
