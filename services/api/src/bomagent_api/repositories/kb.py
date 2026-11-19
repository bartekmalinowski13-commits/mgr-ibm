"""SQL of the knowledge-base document list (``kb.documents``). Writes go through
``bomagent_kb.KnowledgeBase``; this module only reads the API's view of a document."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.repositories.tables import kb_chunks, kb_documents

_d = kb_documents
_CHUNKS = (
    select(func.count()).where(kb_chunks.c.document_id == _d.c.id).scalar_subquery().label("chunks")
)
_DOCUMENT_COLS = (
    _d.c.id,
    _d.c.scope,
    _d.c.title,
    _d.c.kind,
    _d.c.manufacturer,
    _d.c.status,
    _d.c.error,
    _d.c.size_bytes,
    _d.c.created_at,
    _d.c.indexed_at,
    _CHUNKS,
)


async def get_document(conn: AsyncConnection, doc_id: uuid.UUID) -> dict[str, Any]:
    """A document that is known to exist (the caller has just created or found it)."""
    row = (await conn.execute(select(*_DOCUMENT_COLS).where(_d.c.id == doc_id))).one()
    return dict(row._mapping)


async def find_current(conn: AsyncConnection, sha256: str) -> uuid.UUID | None:
    """The organisation's current document with this content, if any."""
    found = (
        await conn.execute(
            select(_d.c.id).where(
                _d.c.scope == "tenant",
                _d.c.tenant_id == func.app.current_tenant_id(),
                _d.c.sha256 == sha256,
                _d.c.superseded_at.is_(None),
            )
        )
    ).scalar()
    return None if found is None else uuid.UUID(str(found))


async def list_page(
    conn: AsyncConnection, *, scope: str, after: ColumnElement[bool] | None, limit: int
) -> list[dict[str, Any]]:
    """Current (not superseded) documents of a scope, newest first."""
    stmt = select(*_DOCUMENT_COLS).where(_d.c.scope == scope, _d.c.superseded_at.is_(None))
    if after is not None:
        stmt = stmt.where(after)
    stmt = stmt.order_by(_d.c.created_at.desc(), _d.c.id.desc()).limit(limit)
    return [dict(r._mapping) for r in await conn.execute(stmt)]
