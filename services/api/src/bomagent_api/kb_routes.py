"""REST API v1: the organisation's knowledge base (datasheets, application notes, standards).

Tenant documents are registered first (metadata + SHA-256), uploaded straight to S3 with a
presigned PUT under the tenant prefix, then queued for the kb-indexer, which extracts,
chunks, screens for prompt injection and embeds them (ADR-0008). Listing shows the
organisation's own documents and the shared global corpus; RLS hides other tenants.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bomagent_api.auth import CAN_READ, CAN_WRITE, require
from bomagent_api.routes import (
    _FILENAME,
    Ctx,
    Page,
    Svc,
    UploadTarget,
    _In,
    _source_ip,
    conflict,
    not_found,
)
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.problems import ProblemError
from bomagent_common.storage import tenant_key
from bomagent_common.tenancy import tenant_scope
from bomagent_kb import DocumentMeta, Scope, get_document, list_documents, register_document

KB_UPLOADED = "kb.document.uploaded"
MAX_BYTES = 50 * 1024 * 1024
Kind = Literal[
    "datasheet", "application_note", "standard", "component_library", "correction", "other"
]
Mime = Literal["application/pdf", "text/markdown", "text/plain", "text/html"]

router = APIRouter(prefix="/v1/kb", tags=["knowledge-base"])


class KbDocumentIn(_In):
    filename: str = Field(pattern=_FILENAME)
    title: str = Field(min_length=1, max_length=500)
    kind: Kind = "datasheet"
    manufacturer: str = Field(default="", max_length=200)
    mime_type: Mime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_BYTES)


class KbDocument(BaseModel):
    id: uuid.UUID
    scope: Literal["global", "tenant"]
    title: str
    kind: str
    manufacturer: str
    mime_type: str
    sha256: str
    size_bytes: int
    status: Literal["pending", "indexing", "indexed", "failed"]
    error: str | None = None
    created_by: str
    created_at: datetime
    indexed_at: datetime | None = None


class KbDocumentCreated(KbDocument):
    upload: UploadTarget | None = Field(
        default=None,
        description="Absent when the same file is already indexed (or being indexed).",
    )


def _doc(row: dict[str, object]) -> KbDocument:
    return KbDocument.model_validate(row)


@router.post(
    "/documents",
    status_code=201,
    response_model=KbDocumentCreated,
    responses={200: {"model": KbDocumentCreated, "description": "Already in the knowledge base"}},
)
async def create_document(
    body: KbDocumentIn, ctx: Ctx, svc: Svc
) -> KbDocumentCreated | JSONResponse:
    require(*CAN_WRITE)(ctx)
    doc_id = uuid.uuid4()
    key = tenant_key(ctx.tenant_id, "kb", str(doc_id), body.filename)
    meta = DocumentMeta(
        title=body.title,
        mime_type=body.mime_type,
        sha256=body.sha256,
        size_bytes=body.size_bytes,
        kind=body.kind,
        manufacturer=body.manufacturer,
        object_key=key,
    )
    # tenant_scope: the registry writes its audit event (kb.document.created) in this context
    with tenant_scope(ctx):
        async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
            stored_id, created = await register_document(
                conn, meta, scope=Scope.TENANT, created_by=ctx.actor_id, doc_id=doc_id
            )
            row = await get_document(conn, stored_id)
    if row is None:  # pragma: no cover - just written in this tenant
        raise not_found("document")
    if not created and row["status"] in ("indexing", "indexed"):
        existing = KbDocumentCreated.model_validate(_doc(row).model_dump())
        return JSONResponse(existing.model_dump(mode="json"), status_code=200)
    # new document, or an earlier registration whose upload never finished: (re)issue the URL
    key = str(row["object_key"])
    with tenant_scope(ctx):
        url = await svc.store.presign_put(key)
    doc = KbDocumentCreated.model_validate(
        _doc(row).model_dump() | {"upload": UploadTarget(filename=key.rsplit("/", 1)[-1], url=url)}
    )
    if created:
        return doc
    return JSONResponse(doc.model_dump(mode="json"), status_code=200)


@router.post("/documents/{document_id}/complete", status_code=202, response_model=KbDocument)
async def complete_document(
    document_id: uuid.UUID, request: Request, ctx: Ctx, svc: Svc
) -> KbDocument:
    """The file is in S3: queue it for extraction, injection screening and embedding."""
    require(*CAN_WRITE)(ctx)
    if svc.kb_queue is None:
        raise ProblemError(
            503, "Service Unavailable", "knowledge-base indexing is not configured", slug="kb-off"
        )
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await get_document(conn, document_id)
        if row is None or row["scope"] != Scope.TENANT.value:
            raise not_found("document")
        if row["status"] not in ("pending", "failed"):
            raise conflict("document is already being indexed or indexed")
        await emit_audit(
            conn,
            AuditEvent(
                action="kb.document.upload_complete",
                object_type="kb_document",
                object_id=str(document_id),
                source_ip=_source_ip(request),
            ),
            ctx,
        )
    filename = str(row["object_key"]).rsplit("/", 1)[-1]
    await svc.kb_queue.send(
        Message.create(
            KB_UPLOADED,
            ctx,
            {
                "document_id": str(document_id),
                "object_key": str(row["object_key"]),
                "filename": filename,
            },
        )
    )
    return _doc(row)


@router.get("/documents", response_model=Page[KbDocument])
async def list_kb_documents(
    ctx: Ctx,
    svc: Svc,
    scope: Literal["tenant", "global"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> Page[KbDocument]:
    require(*CAN_READ)(ctx)
    try:
        async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
            rows, nxt = await list_documents(
                conn, scope=Scope(scope) if scope else None, limit=limit, cursor=cursor
            )
    except ValueError as exc:
        raise ProblemError(400, "Bad Request", str(exc), slug="bad-cursor") from exc
    return Page[KbDocument](items=[_doc(r) for r in rows], next_cursor=nxt)


@router.get("/documents/{document_id}", response_model=KbDocument)
async def get_kb_document(document_id: uuid.UUID, ctx: Ctx, svc: Svc) -> KbDocument:
    require(*CAN_READ)(ctx)
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await get_document(conn, document_id)
    if row is None:
        raise not_found("document")
    return _doc(row)
