"""Hybrid retrieval over the synthetic corpus (integration, needs PostgreSQL+pgvector)."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from bomagent_common.audit import verify_chain
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, DocumentNotFoundError, Scope, extract
from bomagent_testing.kb import load_queries
from bomagent_testing.pdf import make_pdf

pytestmark = pytest.mark.integration


def recall_at(results, expected_titles, k):
    found = sum(
        1
        for hits, want in zip(results, expected_titles, strict=True)
        if want in [h.title for h in hits[:k]]
    )
    return found / len(expected_titles)


async def test_recall_at_k_on_fixture_queries(app_engine, make_tenant, kb, global_corpus):
    queries = load_queries()
    tenant = await make_tenant()
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            results = await kb.search_many(conn, [q["q"] for q in queries], k=5)
    expected = [q["doc"] for q in queries]
    r1, r5 = recall_at(results, expected, 1), recall_at(results, expected, 5)
    print(f"recall@1={r1:.2f} recall@5={r5:.2f} (n={len(queries)})")
    assert r5 >= 0.9
    assert r1 >= 0.6


async def test_exact_mpn_query_hits_ordering_chunk(app_engine, make_tenant, kb, global_corpus):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        hits = await kb.search(conn, "GRM188R71H473KA61D", k=3)
    assert hits[0].title == "murata-grm188"
    assert hits[0].text_rank is not None
    citation = hits[0].citation()
    assert citation.scope == "global"
    assert citation.page == 1
    assert "GRM188" in citation.quote


async def test_injection_document_is_flagged_and_ranked_last(
    app_engine, make_tenant, kb, global_corpus
):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        flagged = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM kb.chunks c JOIN kb.documents d ON d.id = c.document_id"
                    " WHERE d.title = 'malicious-injection' AND c.injection_suspect"
                )
            )
        ).scalar()
        top = await kb.search(conn, "10 kΩ 0603 thick film resistor XR0603-10K", k=5)
        everything = await kb.search(conn, "10 kΩ 0603 thick film resistor XR0603-10K", k=100)
    assert flagged >= 1
    assert not any(h.injection_suspect for h in top)
    suspicious = [i for i, h in enumerate(everything) if h.injection_suspect]
    assert suspicious, "the adversarial chunk is a candidate"
    assert suspicious == list(range(suspicious[0], len(everything)))  # ranked last


async def test_part_catalogue(app_engine, make_tenant, kb, global_corpus):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        known = await kb.known_mpns(conn)
        parts = await kb.find_parts(conn, "rc0603fr-0710")
    assert {"RC0603FR-0710KL", "MCP1700T-3302E/TT", "AD8232ACPZ-R7"} <= known
    assert {p["mpn"] for p in parts} >= {"RC0603FR-0710KL", "RC0603FR-0710ML"}
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        assert await kb.find_parts(conn, "%") == []  # LIKE wildcards are escaped


async def test_tenant_document_pdf_indexing_with_audit(app_engine, make_tenant, kb):
    tenant = await make_tenant()
    pdf = make_pdf(["Company component library", "Ordering information ACME-REG-033 regulator"])
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            doc_id = await kb.add_document(
                conn,
                DocumentMeta(
                    title="ACME library",
                    mime_type="application/pdf",
                    sha256=hashlib.sha256(pdf).hexdigest(),
                    size_bytes=len(pdf),
                    kind="component_library",
                ),
                scope=Scope.TENANT,
                created_by=tenant.actor_id,
            )
            again = await kb.add_document(
                conn,
                DocumentMeta(
                    title="dup",
                    mime_type="application/pdf",
                    sha256=hashlib.sha256(pdf).hexdigest(),
                    size_bytes=len(pdf),
                ),
                scope=Scope.TENANT,
                created_by=tenant.actor_id,
            )
            result = await kb.index_document(conn, doc_id, extract("lib.pdf", pdf))
            hits = await kb.search(conn, "ACME-REG-033", k=3, kinds=["component_library"])
            actions = (
                (await conn.execute(text("SELECT action FROM audit.events ORDER BY seq")))
                .scalars()
                .all()
            )
            chain = await verify_chain(conn, tenant.tenant_id)
    assert again == doc_id
    assert result.chunks == 2
    assert "ACME-REG-033" in result.parts
    assert hits[0].document_id == doc_id
    assert hits[0].scope == "tenant"
    assert actions == ["kb.document.created", "kb.document.indexed"]
    assert chain.ok


async def test_snapshot_freezes_document_set(app_engine, make_tenant, kb, global_corpus):
    tenant = await make_tenant()
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            snap = await kb.snapshot(conn)
            assert snap == await kb.snapshot(conn)  # deterministic for the same set
            await kb.add_correction(
                conn,
                mpn="ACME-RES-10K",
                manufacturer="ACME",
                note="approved 10k resistor",
                attributes={"value": "10k"},
            )
            fresh = await kb.search(conn, "ACME-RES-10K approved", k=3)
            frozen = await kb.search(conn, "ACME-RES-10K approved", k=3, snapshot_id=snap)
            new_snap = await kb.snapshot(conn)
            parts = await kb.find_parts(conn, "ACME-RES")
    assert fresh[0].kind == "correction"
    assert all(h.kind != "correction" for h in frozen)
    assert new_snap != snap
    assert parts[0]["source"] == "user_correction"
    assert parts[0]["scope"] == "tenant"


async def test_supersede_and_failure(app_engine, make_tenant, kb):
    tenant = await make_tenant()
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            ids = []
            for version in ("v1 ACMEPART-0001 ordering part number", "v2 ACMEPART-0001 rev B"):
                data = version.encode()
                doc = await kb.add_document(
                    conn,
                    DocumentMeta(
                        title=version[:2],
                        mime_type="text/plain",
                        sha256=hashlib.sha256(data).hexdigest(),
                        size_bytes=len(data),
                    ),
                    scope=Scope.TENANT,
                    created_by="u",
                )
                await kb.index_document(conn, doc, extract("d.txt", data))
                ids.append(doc)
            await kb.supersede(conn, ids[0], ids[1])
            hits = await kb.search(conn, "ACMEPART-0001", k=20)
            await kb.mark_failed(conn, ids[1], "boom")
            status = (
                await conn.execute(
                    text("SELECT status FROM kb.documents WHERE id = :i"), {"i": ids[1]}
                )
            ).scalar()
    titles = {h.title for h in hits}
    assert "v2" in titles
    assert "v1" not in titles
    assert status == "failed"


async def test_unknown_document_and_snapshot(app_engine, make_tenant, kb):
    import uuid

    from bomagent_kb import ExtractedDocument

    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        with pytest.raises(DocumentNotFoundError):
            await kb.index_document(conn, uuid.uuid4(), ExtractedDocument([], "text/plain"))
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        with pytest.raises(DocumentNotFoundError):
            await kb.search(conn, "x", snapshot_id="kbs_missing")
    async with platform_transaction(app_engine) as conn:
        assert await kb.search_many(conn, []) == []
