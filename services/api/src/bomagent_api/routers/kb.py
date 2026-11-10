"""Knowledge base of the organisation (ADR-0008) and a read-only view of the global corpus.

Uploads are stored under the tenant prefix and announced to the ``kb-indexer`` through
the outbox; extraction and chunking never run in the API process. Document text is
untrusted: it is indexed with prompt-injection flagging and never shown as instructions.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, Request, UploadFile
from sqlalchemy import text

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.routers.projects import deliver_now
from bomagent_api.schemas import KbDocument, Page, problem_responses
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import tenant_key
from bomagent_kb.extract import mime_for
from bomagent_kb.store import DocumentMeta, Scope

router = APIRouter(
    prefix="/v1/kb",
    tags=["knowledge base"],
    responses=problem_responses(400, 401, 403, 413, 415, 422, 429),
)
MAX_DOCUMENT = 32 * 1024 * 1024
ALLOWED = {"application/pdf", "text/markdown", "text/plain"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]")
COLS = (
    "d.id, d.scope, d.title, d.kind, d.manufacturer, d.status, d.error, d.size_bytes,"
    " d.created_at, d.indexed_at,"
    " (SELECT count(*) FROM kb.chunks c WHERE c.document_id = d.id) AS chunks"
)


async def _get(conn: Any, doc_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(f"SELECT {COLS} FROM kb.documents d WHERE d.id = :i"),  # noqa: S608
            {"i": doc_id},
        )
    ).one()
    return dict(row._mapping)


@router.get("/documents", summary="Knowledge-base documents (organisation or global corpus)")
async def list_documents(
    request: Request,
    ctx: OrgContext,
    scope: Literal["tenant", "global"] = "tenant",
    cursor: str | None = None,
    limit: int = 25,
) -> Page[KbDocument]:
    require(ctx, "kb.read")
    params: dict[str, Any] = {"lim": clamp(limit) + 1, "scope": scope}
    sql = (
        f"SELECT {COLS} FROM kb.documents d WHERE d.scope = :scope"  # noqa: S608
        " AND d.superseded_at IS NULL"
        f"{page_clause(cursor, params, alias='d')} ORDER BY d.created_at DESC, d.id DESC LIMIT :lim"
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[KbDocument](items=[KbDocument(**r) for r in rows], next_cursor=nxt)


@router.post(
    "/documents", status_code=201, summary="Add a document to the organisation's knowledge"
)
async def upload_document(
    request: Request,
    ctx: OrgContext,
    file: UploadFile,
    kind: Annotated[
        Literal["datasheet", "application_note", "standard", "component_library", "other"],
        Form(),
    ] = "datasheet",
    manufacturer: Annotated[str, Form(max_length=120)] = "",
) -> KbDocument:
    """Duplicates (same content) return the existing document."""
    require(ctx, "kb.write")
    name = _SAFE_NAME.sub("_", (file.filename or "document").rsplit("/", 1)[-1])[:200] or "document"
    mime = mime_for(name)
    if mime not in ALLOWED:
        raise ProblemError(
            415,
            "Unsupported Media Type",
            "upload a PDF, Markdown or text file",
            slug="unsupported-type",
        )
    data = await file.read(MAX_DOCUMENT + 1)
    if len(data) > MAX_DOCUMENT:
        raise ProblemError(
            413, "Payload Too Large", "document larger than 32 MB", slug="file-too-large"
        )
    if "\x00" in manufacturer:
        raise ProblemError(422, "Unprocessable Entity", "NUL characters are not allowed")
    store = request.app.state.store
    kb = request.app.state.kb
    key = tenant_key(ctx.tenant_id, "kb", str(uuid.uuid4()), name)
    await store.put(key, data, "application/octet-stream")
    outbox_id = None
    try:
        async with tenant_transaction(request.app.state.engine) as conn:
            doc_id = await kb.add_document(
                conn,
                DocumentMeta(
                    title=name,
                    mime_type=mime,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    kind=kind,
                    manufacturer=manufacturer.strip(),
                    object_key=key,
                ),
                scope=Scope.TENANT,
                created_by=ctx.actor_id,
            )
            doc = await _get(conn, doc_id)
            if doc["status"] == "pending" and doc["indexed_at"] is None:
                outbox_id = await enqueue(
                    conn,
                    "kb",
                    Message.create(
                        "kb.document.uploaded",
                        ctx,
                        {"document_id": str(doc_id), "object_key": key, "filename": name},
                    ),
                )
    except BaseException:
        await store.delete(key)
        raise
    if outbox_id is None:  # duplicate of an existing document: keep only the original object
        await store.delete(key)
    else:
        await deliver_now(request, ctx.tenant_id, outbox_id)
    return KbDocument(**doc)
