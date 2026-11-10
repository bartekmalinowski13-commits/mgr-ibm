"""Knowledge-base document registry (no embeddings needed): register, read, list.

Used by ``KnowledgeBase`` and by the API, which registers a tenant document before its
file is uploaded and lists documents for the knowledge-base screen. Callers open the
connection in the right RLS context (see ``store`` module docstring).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.records import decode_cursor, encode_cursor
from bomagent_common.tenancy import require_tenant
from bomagent_kb.store_types import DocumentMeta, Scope

_COLUMNS = (
    "id, scope, title, kind, manufacturer, mime_type, sha256, size_bytes, status, error,"
    " object_key, created_by, created_at, indexed_at"
)


async def register_document(
    conn: AsyncConnection,
    meta: DocumentMeta,
    *,
    scope: Scope,
    created_by: str,
    doc_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, bool]:
    """Register a document (status ``pending``). Returns ``(id, created)``; for content
    already in the same scope (same SHA-256) the existing id and ``False``."""
    tenant_id = require_tenant().tenant_id if scope == Scope.TENANT else None
    existing = (
        await conn.execute(
            text(
                "SELECT id FROM kb.documents WHERE sha256 = :sha AND scope = :scope"
                " AND tenant_id IS NOT DISTINCT FROM :tid AND superseded_at IS NULL"
            ),
            {"sha": meta.sha256, "scope": scope.value, "tid": tenant_id},
        )
    ).scalar()
    if existing is not None:
        return uuid.UUID(str(existing)), False
    doc_id = doc_id or uuid.uuid4()
    await conn.execute(
        text(
            """INSERT INTO kb.documents (id, tenant_id, scope, title, kind, manufacturer,
                 source_uri, object_key, mime_type, sha256, size_bytes, created_by)
               VALUES (:id, :tid, :scope, :title, :kind, :mfr, :uri, :key, :mime, :sha,
                 :size, :by)"""
        ),
        {
            "id": doc_id,
            "tid": tenant_id,
            "scope": scope.value,
            "title": meta.title[:500],
            "kind": meta.kind,
            "mfr": meta.manufacturer,
            "uri": meta.source_uri,
            "key": meta.object_key,
            "mime": meta.mime_type,
            "sha": meta.sha256,
            "size": meta.size_bytes,
            "by": created_by,
        },
    )
    if scope == Scope.TENANT:
        await emit_audit(
            conn,
            AuditEvent(
                action="kb.document.created",
                object_type="kb_document",
                object_id=str(doc_id),
                after={"title": meta.title, "kind": meta.kind, "sha256": meta.sha256},
            ),
        )
    return doc_id, True


async def get_document(conn: AsyncConnection, doc_id: uuid.UUID) -> dict[str, Any] | None:
    """A document visible in the current RLS context (own tenant or global), or None."""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_COLUMNS} FROM kb.documents WHERE id = :id"),  # noqa: S608 - constant columns
                {"id": doc_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def list_documents(
    conn: AsyncConnection,
    *,
    scope: Scope | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Current (not superseded) documents, newest first, keyset-paginated."""
    where = "superseded_at IS NULL"
    params: dict[str, Any] = {"limit": limit + 1}
    if scope is not None:
        where += " AND scope = :scope"
        params["scope"] = scope.value
    if cursor:
        ts, rid = decode_cursor(cursor)
        where += " AND (created_at, id) < (:c_ts, :c_id)"
        params |= {"c_ts": ts, "c_id": rid}
    rows = [
        dict(r)
        for r in (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM kb.documents WHERE {where}"  # noqa: S608 - built from constants
                    " ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                params,
            )
        ).mappings()
    ]
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"])
    return rows, nxt
