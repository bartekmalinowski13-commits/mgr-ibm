"""Knowledge-base isolation: global corpus read-only for tenants, tenant spaces private
(ADR-0008). Marker ``isolation`` - blocks merges."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, Scope, extract
from bomagent_testing.kb import make_kb

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


def _meta(text_: str, title: str) -> DocumentMeta:
    data = text_.encode()
    return DocumentMeta(
        title=title,
        mime_type="text/plain",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


async def _tenant_doc(engine, tenant, secret: str) -> uuid.UUID:
    kb = make_kb()
    with tenant_scope(tenant):
        async with tenant_transaction(engine) as conn:
            doc = await kb.add_document(
                conn, _meta(secret, f"secret {secret}"), scope=Scope.TENANT, created_by="u"
            )
            await kb.index_document(
                conn,
                doc,
                extract("s.txt", secret.encode()),
                extra_mpns=[secret.split(maxsplit=1)[0]],
            )
    return doc


async def _global_doc(platform_engine, body: str) -> uuid.UUID:
    kb = make_kb()
    async with platform_transaction(platform_engine) as conn:
        doc = await kb.add_document(
            conn, _meta(body, "public"), scope=Scope.GLOBAL, created_by="pipeline"
        )
        await kb.index_document(conn, doc, extract("p.txt", body.encode()))
    return doc


async def test_tenant_cannot_retrieve_other_tenants_documents(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await _tenant_doc(app_engine, b, "BSECRET-4242 confidential part")
    kb = make_kb()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        hits = await kb.search(conn, "BSECRET-4242 confidential part", k=20)
        mpns = await kb.known_mpns(conn)
        parts = await kb.find_parts(conn, "BSECRET")
        docs = (
            await conn.execute(text("SELECT count(*) FROM kb.documents WHERE title LIKE 'secret%'"))
        ).scalar()
    assert all("BSECRET" not in h.content for h in hits)
    assert "BSECRET-4242" not in mpns
    assert parts == []
    assert docs == 0
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        assert "BSECRET-4242" in await kb.known_mpns(conn)


async def test_global_corpus_visible_to_all_tenants_and_without_context(
    app_engine, platform_engine, make_tenant
):
    gdoc = await _global_doc(platform_engine, "GLOBALPART-777 public datasheet ordering")
    kb = make_kb()
    for tenant in (await make_tenant(), await make_tenant()):
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            hits = await kb.search(conn, "GLOBALPART-777", k=5)
        assert hits[0].document_id == gdoc
    async with platform_transaction(app_engine) as conn:
        assert (await kb.search(conn, "GLOBALPART-777", k=5))[0].document_id == gdoc


async def test_tenant_cannot_modify_or_create_global_rows(app_engine, platform_engine, make_tenant):
    gdoc = await _global_doc(platform_engine, "GLOBALPART-888 public")
    a = await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        upd = await conn.execute(
            text("UPDATE kb.documents SET title = 'x' WHERE id = :i"), {"i": gdoc}
        )
        dele = await conn.execute(text("DELETE FROM kb.chunks WHERE document_id = :i"), {"i": gdoc})
    assert upd.rowcount == 0
    assert dele.rowcount == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb.documents (id, scope, title, mime_type, sha256, size_bytes,"
                    " created_by) VALUES (:i, 'global', 't', 'text/plain', :s, 1, 'u')"
                ),
                {"i": uuid.uuid4(), "s": "a" * 64},
            )
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb.parts (id, scope, tenant_id, mpn) VALUES"
                    " (:i, 'tenant', :t, 'X')"
                ),
                {"i": uuid.uuid4(), "t": uuid.uuid4()},
            )


async def test_platform_role_cannot_touch_tenant_rows(platform_engine, app_engine, make_tenant):
    a = await make_tenant()
    doc = await _tenant_doc(app_engine, a, "ATENANT-1 private")
    async with platform_transaction(platform_engine) as conn:
        seen = (
            await conn.execute(text("SELECT count(*) FROM kb.documents WHERE id = :i"), {"i": doc})
        ).scalar()
        upd = await conn.execute(
            text("UPDATE kb.chunks SET content = 'x' WHERE document_id = :i"), {"i": doc}
        )
    assert seen == 0
    assert upd.rowcount == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb.parts (id, scope, tenant_id, mpn) VALUES"
                    " (:i, 'tenant', :t, 'X')"
                ),
                {"i": uuid.uuid4(), "t": a.tenant_id},
            )


async def test_rows_cannot_be_attached_to_a_foreign_document(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    b_doc = await _tenant_doc(app_engine, b, "BDOC-1 private")
    with pytest.raises(DBAPIError, match="scope and tenant of its document"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb.parts (id, scope, tenant_id, document_id, mpn) VALUES"
                    " (:i, 'tenant', :t, :d, 'STOLEN')"
                ),
                {"i": uuid.uuid4(), "t": a.tenant_id, "d": b_doc},
            )


async def test_snapshots_are_private(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    kb = make_kb()
    await _tenant_doc(app_engine, b, "BSNAP-1 private")
    with tenant_scope(b):
        async with tenant_transaction(app_engine) as conn:
            snap = await kb.snapshot(conn)
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        visible = (
            await conn.execute(text("SELECT count(*) FROM kb.snapshots WHERE id = :i"), {"i": snap})
        ).scalar()
    assert visible == 0
