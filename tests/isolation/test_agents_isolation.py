"""Agents read the knowledge base only within their tenant (ADR-0004, ADR-0008).
Marker ``isolation`` - blocks merges."""

from __future__ import annotations

import hashlib

import pytest

from bomagent_agents import KbRetriever
from bomagent_common.db import tenant_transaction
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, Scope, extract
from bomagent_testing.kb import make_kb

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


async def _index(engine, tenant, body: str) -> None:
    kb = make_kb()
    data = body.encode()
    meta = DocumentMeta(
        title="private lib",
        mime_type="text/plain",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    with tenant_scope(tenant):
        await _add(kb, engine, meta, data, body)


async def _add(kb, engine, meta, data, body) -> None:
    async with tenant_transaction(engine) as conn:
        doc = await kb.add_document(conn, meta, scope=Scope.TENANT, created_by="u")
        await kb.index_document(
            conn, doc, extract("lib.txt", data), extra_mpns=[body.split(maxsplit=1)[0]]
        )


async def test_kb_retriever_never_returns_another_tenants_parts(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await _index(
        app_engine, b, "ZZPRIVATE-9911 ordering information confidential resistor 10k 0603"
    )
    await _index(app_engine, a, "AAOWN-1234 ordering information own capacitor 100n 0603")
    kb = make_kb()
    ra, rb = KbRetriever(kb, app_engine, a.tenant_id), KbRetriever(kb, app_engine, b.tenant_id)
    hits_a = (await ra.search_many(["ZZPRIVATE-9911 confidential resistor"], 20))[0]
    assert all("ZZPRIVATE" not in h.content for h in hits_a)
    assert "ZZPRIVATE-9911" not in await ra.known_mpns()
    assert "AAOWN-1234" in await ra.known_mpns()
    hits_b = (await rb.search_many(["ZZPRIVATE-9911 confidential resistor"], 5))[0]
    assert hits_b
    assert "ZZPRIVATE-9911" in hits_b[0].content
    assert hits_b[0].scope == "tenant"
