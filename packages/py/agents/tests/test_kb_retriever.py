"""KbRetriever uses tenant context: RLS hides other tenants' documents (isolation)."""

from __future__ import annotations

import hashlib

import pytest

from bomagent_agents.retrieval import KbRetriever
from bomagent_common.db import tenant_transaction
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, Scope, extract
from bomagent_testing.kb import make_kb

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


async def test_retriever_sees_only_own_tenant_documents(app_engine, make_tenant):
    kb = make_kb()
    a, b = await make_tenant(), await make_tenant()
    text = b"Ordering information\nPart number SECRETB-4711 private regulator"
    with tenant_scope(b):
        async with tenant_transaction(app_engine) as conn:
            doc = await kb.add_document(
                conn,
                DocumentMeta(
                    title="b-lib",
                    mime_type="text/plain",
                    sha256=hashlib.sha256(text).hexdigest(),
                    size_bytes=len(text),
                ),
                scope=Scope.TENANT,
                created_by="u",
            )
            await kb.index_document(conn, doc, extract("b.txt", text))
    (ev_b,) = await KbRetriever(kb, app_engine, b.tenant_id).evidence(["SECRETB-4711"], 5)
    (ev_a,) = await KbRetriever(kb, app_engine, a.tenant_id).evidence(["SECRETB-4711"], 5)
    assert any("SECRETB-4711" in h.content for h in ev_b.hits)
    assert not any("SECRETB-4711" in h.content for h in ev_a.hits)
    assert "SECRETB-4711" in await KbRetriever(kb, app_engine, b.tenant_id).known_mpns()
    assert "SECRETB-4711" not in await KbRetriever(kb, app_engine, a.tenant_id).known_mpns()
