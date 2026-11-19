"""Knowledge-base documents of the organisation (ADR-0008): list and upload (ARCH-04)."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.pagination import clamp, encode_cursor, page_filter
from bomagent_api.plans import check_storage, plan_of
from bomagent_api.repositories import kb as repo
from bomagent_api.repositories.tables import kb_documents
from bomagent_api.schemas import KbDocument, Page
from bomagent_api.services.outbox import deliver_now
from bomagent_api.services.projects import delete_objects
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message, Queue
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import ObjectStore, tenant_key
from bomagent_common.tenancy import TenantContext
from bomagent_kb import KnowledgeBase
from bomagent_kb.extract import mime_for
from bomagent_kb.store import DocumentMeta, Scope

ALLOWED = {"application/pdf", "text/markdown", "text/plain"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]")
DocumentKind = Literal["datasheet", "application_note", "standard", "component_library", "other"]


def safe_filename(filename: str | None) -> str:
    """Last path segment of a client file name with anything but ``[A-Za-z0-9._-]`` replaced."""
    return _SAFE_NAME.sub("_", (filename or "document").rsplit("/", 1)[-1])[:200] or "document"


def mime_of_upload(name: str) -> str:
    """MIME type of an accepted upload; PDF, Markdown and plain text only."""
    mime = mime_for(name)
    if mime not in ALLOWED:
        raise ProblemError(
            415,
            "Unsupported Media Type",
            "upload a PDF, Markdown or text file",
            slug="unsupported-type",
        )
    return mime


async def list_documents(
    engine: AsyncEngine, *, scope: Literal["tenant", "global"], cursor: str | None, limit: int
) -> Page[KbDocument]:
    after = page_filter(cursor, kb_documents.c.created_at, kb_documents.c.id)
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_page(conn, scope=scope, after=after, limit=clamp(limit) + 1)
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[KbDocument](items=[KbDocument(**r) for r in rows], next_cursor=nxt)


async def upload_document(
    engine: AsyncEngine,
    store: ObjectStore,
    kb: KnowledgeBase,
    queues: Mapping[str, Queue],
    ctx: TenantContext,
    *,
    name: str,
    mime: str,
    data: bytes,
    kind: DocumentKind,
    manufacturer: str,
) -> tuple[KbDocument, bool]:
    """The document and whether it was created. A duplicate (same content) returns the
    existing document: nothing is queued and the uploaded object is removed again.

    The object is stored before the tenant lock is taken (its key is unique), so a slow
    upload never holds up the organisation's other uploads; the lock then serialises the
    duplicate check, the storage quota (design files + KB documents) and the insert."""
    if "\x00" in manufacturer:
        raise ProblemError(422, "Unprocessable Entity", "NUL characters are not allowed")
    key = tenant_key(ctx.tenant_id, "kb", str(uuid.uuid4()), name)
    sha256 = hashlib.sha256(data).hexdigest()
    await store.put(key, data, "application/octet-stream")
    outbox_id = None
    try:
        async with tenant_transaction(engine) as conn:
            await plan_of(conn, lock=True)
            doc_id = await repo.find_current(conn, sha256)
            created = False
            if doc_id is None:
                await check_storage(conn, len(data))
                doc_id, created = await kb.register_document(
                    conn,
                    DocumentMeta(
                        title=name,
                        mime_type=mime,
                        sha256=sha256,
                        size_bytes=len(data),
                        kind=kind,
                        manufacturer=manufacturer.strip(),
                        object_key=key,
                    ),
                    scope=Scope.TENANT,
                    created_by=ctx.actor_id,
                )
            if created:  # a pending duplicate already has its own message
                outbox_id = await enqueue(
                    conn,
                    "kb",
                    Message.create(
                        "kb.document.uploaded",
                        ctx,
                        {"document_id": str(doc_id), "object_key": key, "filename": name},
                    ),
                )
            doc = await repo.get_document(conn, doc_id)
    except BaseException:
        await delete_objects(store, ctx.tenant_id, [key])
        raise
    if outbox_id is None:  # duplicate of an existing document: keep only the original object
        await delete_objects(store, ctx.tenant_id, [key])
    else:
        await deliver_now(engine, queues, ctx.tenant_id, outbox_id)
    return KbDocument(**doc), created
