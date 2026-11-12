"""kb-indexer: queue message -> object store -> extraction -> tenant-scoped index."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text

from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, Message, process_one
from bomagent_common.storage import InMemoryObjectStore, tenant_key
from bomagent_common.tenancy import TenantContext, tenant_scope
from bomagent_kb import DocumentMeta, Scope
from bomagent_kb_indexer.app import Settings, build_handler
from bomagent_kb_indexer.handler import (
    GLOBAL_UPLOAD,
    PLATFORM_TENANT,
    TENANT_UPLOAD,
    KbIndexer,
    RejectedMessageError,
)
from bomagent_testing.kb import make_kb
from bomagent_testing.pdf import make_pdf

pytestmark = pytest.mark.integration


async def _register(app_engine, tenant, kb, data: bytes, name: str) -> tuple[uuid.UUID, str]:
    key = tenant_key(tenant.tenant_id, "kb", name)
    with tenant_scope(tenant):
        async with tenant_transaction(app_engine) as conn:
            doc = await kb.add_document(
                conn,
                DocumentMeta(
                    title=name,
                    mime_type="application/pdf",
                    object_key=key,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                ),
                scope=Scope.TENANT,
                created_by=tenant.actor_id,
            )
    return doc, key


async def test_tenant_upload_is_indexed(app_engine, make_tenant):
    tenant = await make_tenant()
    kb = make_kb()
    store = InMemoryObjectStore(enforce_tenant=False)
    data = make_pdf(["Ordering information TENANTPART-99 regulator"])
    doc, key = await _register(app_engine, tenant, kb, data, "lib.pdf")
    store.objects[key] = data
    indexer = KbIndexer(kb=kb, app_engine=app_engine, tenant_store=store)
    queue = InMemoryQueue()
    await queue.send(
        Message.create(
            TENANT_UPLOAD,
            tenant,
            {"document_id": str(doc), "object_key": key, "filename": "lib.pdf"},
        )
    )
    (item,) = await queue.receive()
    assert await process_one(queue, item, indexer.handle)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        status = (
            await conn.execute(text("SELECT status FROM kb.documents WHERE id = :i"), {"i": doc})
        ).scalar()
        assert "TENANTPART-99" in await kb.known_mpns(conn)
    assert status == "indexed"


async def test_corrupt_file_marks_document_failed_and_acks(app_engine, make_tenant):
    tenant = await make_tenant()
    kb = make_kb()
    store = InMemoryObjectStore(enforce_tenant=False)
    doc, key = await _register(app_engine, tenant, kb, b"%PDF-broken", "bad.pdf")
    store.objects[key] = b"%PDF-broken"
    indexer = KbIndexer(kb=kb, app_engine=app_engine, tenant_store=store)
    queue = InMemoryQueue()
    await queue.send(
        Message.create(
            TENANT_UPLOAD,
            tenant,
            {"document_id": str(doc), "object_key": key, "filename": "bad.pdf"},
        )
    )
    (item,) = await queue.receive()
    assert await process_one(queue, item, indexer.handle)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT status, error FROM kb.documents WHERE id = :i"), {"i": doc}
            )
        ).one()
    assert row.status == "failed"
    assert "PDF" in row.error


async def test_foreign_object_key_and_forged_global_messages_are_rejected(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    indexer = KbIndexer(kb=make_kb(), app_engine=app_engine, tenant_store=InMemoryObjectStore())
    with pytest.raises(RejectedMessageError, match="tenant prefix"):
        await indexer.handle(
            Message.create(
                TENANT_UPLOAD,
                a,
                {
                    "document_id": str(uuid.uuid4()),
                    "object_key": tenant_key(b.tenant_id, "x.pdf"),
                    "filename": "x.pdf",
                },
            )
        )
    with pytest.raises(RejectedMessageError, match="only from the platform"):
        await indexer.handle(Message.create(GLOBAL_UPLOAD, a, {"document_id": "x"}))
    system = TenantContext(tenant_id=PLATFORM_TENANT, actor_id="pipeline", actor_type="system")
    with pytest.raises(RejectedMessageError, match="not configured"):
        await indexer.handle(Message.create(GLOBAL_UPLOAD, system, {"document_id": "x"}))
    await indexer.handle(Message.create("unknown.type", a))  # ignored, no error


async def test_global_upload_uses_platform_role(app_engine, platform_engine, make_tenant):
    from bomagent_common.db import platform_transaction

    kb = make_kb()
    data = b"Ordering information GLOBALIDX-55 sensor"
    async with platform_transaction(platform_engine) as conn:
        doc = await kb.add_document(
            conn,
            DocumentMeta(
                title="g",
                mime_type="text/plain",
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            ),
            scope=Scope.GLOBAL,
            created_by="pipeline",
        )
    store = InMemoryObjectStore(enforce_tenant=False)
    store.objects["global/g.txt"] = data
    indexer = KbIndexer(
        kb=kb,
        app_engine=app_engine,
        tenant_store=InMemoryObjectStore(),
        platform_engine=platform_engine,
        global_store=store,
    )
    system = TenantContext(tenant_id=PLATFORM_TENANT, actor_id="pipeline", actor_type="system")
    await indexer.handle(
        Message.create(
            GLOBAL_UPLOAD,
            system,
            {"document_id": str(doc), "object_key": "global/g.txt", "filename": "g.txt"},
        )
    )
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        assert "GLOBALIDX-55" in await kb.known_mpns(conn)


def test_build_handler_requires_database_and_wires_gateway(db_urls):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        build_handler(Settings(environment="test"))
    handler = build_handler(
        Settings(
            environment="test",
            database_url=db_urls.app,
            platform_database_url=db_urls.platform,
            global_bucket="g",
            llm_gateway_url="http://gw",
            llm_gateway_key="k",
        )
    )
    assert handler.__self__.kb.embedder.model == "fake-embedding"
    assert handler.__self__.platform_engine is not None
