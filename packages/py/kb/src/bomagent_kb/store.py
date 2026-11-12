"""Knowledge-base store and hybrid retrieval (ADR-0008).

All methods take an ``AsyncConnection`` opened by the caller in the right RLS context:
``tenant_transaction`` for a tenant (sees global + own rows, writes own rows) or
``platform_transaction`` on the platform engine (writes the global corpus). Isolation is
therefore enforced by PostgreSQL, not by ``WHERE tenant_id = ...`` in this code.

Retrieval = pgvector cosine search + PostgreSQL full-text search, fused with Reciprocal
Rank Fusion, then reranked (lexical reranker by default, pluggable). ``search_many``
embeds all queries in one gateway call (batching, ARCHITECTURE.md §9).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from opentelemetry import trace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_bom.model import KbCitation
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.tenancy import current_tenant, require_tenant
from bomagent_kb.chunking import chunk_document
from bomagent_kb.extract import ExtractedDocument, Page
from bomagent_kb.parts import extract_part_numbers
from bomagent_kb.safety import looks_like_injection, sanitize
from bomagent_llm.embeddings import EmbeddingClient

tracer = trace.get_tracer(__name__)
RRF_K = 60
_WORD = re.compile(r"[A-Za-z0-9µΩ]+(?:[.,][0-9]+)?")


class Scope(StrEnum):
    GLOBAL = "global"
    TENANT = "tenant"


class DocumentNotFoundError(LookupError):
    """Unknown id or not visible in the current tenant context."""


@dataclass(frozen=True)
class DocumentMeta:
    title: str
    mime_type: str
    sha256: str
    size_bytes: int
    kind: str = "datasheet"
    manufacturer: str = ""
    source_uri: str = ""
    object_key: str | None = None


@dataclass(frozen=True)
class IndexResult:
    document_id: uuid.UUID
    chunks: int
    parts: list[str]
    suspicious_chunks: int
    limitations: list[str] = field(default_factory=list)


@dataclass
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    page: int | None
    section: str
    scope: str
    content: str
    kind: str
    manufacturer: str
    injection_suspect: bool
    score: float = 0.0
    vector_rank: int | None = None
    text_rank: int | None = None

    def citation(self, quote_chars: int = 300) -> KbCitation:
        return KbCitation(
            document_id=str(self.document_id),
            chunk_id=str(self.chunk_id),
            page=self.page,
            scope="global" if self.scope == "global" else "tenant",
            quote=self.content[:quote_chars],
        )


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]: ...


class LexicalReranker:
    """Cheap, deterministic reranker: fused score + term overlap + exact token match.

    Suspicious chunks (possible prompt injection) are always ranked last.
    """

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        terms = {t.lower() for t in _WORD.findall(query)}
        for h in hits:
            words = {t.lower() for t in _WORD.findall(h.content)}
            overlap = len(terms & words) / len(terms) if terms else 0.0
            exact = any(len(t) >= 6 and t.upper() in h.content.upper() for t in terms)
            h.score = h.score + 0.02 * overlap + (0.02 if exact else 0.0)
        return sorted(hits, key=lambda h: (h.injection_suspect, -h.score))


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


def _tsquery(query: str) -> str:
    """OR-query of sanitized terms (``to_tsquery`` syntax; no user operators pass through)."""
    terms = {t.lower() for t in _WORD.findall(query) if len(t) > 1}
    return " | ".join(sorted(t.replace(",", ".") for t in terms))


class KnowledgeBase:
    def __init__(self, embedder: EmbeddingClient, reranker: Reranker | None = None) -> None:
        self.embedder = embedder
        self.reranker = reranker or LexicalReranker()

    # ------------------------------------------------------------------ documents
    async def add_document(
        self,
        conn: AsyncConnection,
        meta: DocumentMeta,
        *,
        scope: Scope,
        created_by: str,
    ) -> uuid.UUID:
        """Register a document (status ``pending``); returns the existing id for a
        duplicate (same content in the same scope)."""
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
            return uuid.UUID(str(existing))
        doc_id = uuid.uuid4()
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
        return doc_id

    async def _document(self, conn: AsyncConnection, doc_id: uuid.UUID) -> Any:
        row = (
            await conn.execute(
                text("SELECT id, scope, tenant_id, title FROM kb.documents WHERE id = :id"),
                {"id": doc_id},
            )
        ).first()
        if row is None:
            raise DocumentNotFoundError(str(doc_id))
        return row

    async def index_document(
        self,
        conn: AsyncConnection,
        doc_id: uuid.UUID,
        extracted: ExtractedDocument,
        *,
        extra_mpns: Sequence[str] = (),
        manufacturer: str = "",
    ) -> IndexResult:
        doc = await self._document(conn, doc_id)
        with tracer.start_as_current_span(
            "kb.index_document", attributes={"kb.document_id": str(doc_id), "kb.scope": doc.scope}
        ) as span:
            await conn.execute(
                text("UPDATE kb.documents SET status = 'indexing' WHERE id = :id"), {"id": doc_id}
            )
            await conn.execute(
                text("DELETE FROM kb.chunks WHERE document_id = :id"), {"id": doc_id}
            )
            await conn.execute(
                text("DELETE FROM kb.parts WHERE document_id = :id AND source = 'datasheet'"),
                {"id": doc_id},
            )
            chunks = chunk_document(extracted)
            vectors = await self.embedder.embed([c.content for c in chunks]) if chunks else []
            suspicious = 0
            for chunk, vec in zip(chunks, vectors, strict=True):
                flag = looks_like_injection(chunk.content)
                suspicious += flag
                await conn.execute(
                    text(
                        """INSERT INTO kb.chunks (id, document_id, tenant_id, scope, ordinal, page,
                             section, content, embedding, embedding_model, token_estimate,
                             injection_suspect)
                           VALUES (:id, :doc, :tid, :scope, :ord, :page, :section, :content,
                             CAST(:emb AS vector), :model, :tokens, :flag)"""
                    ),
                    {
                        "id": uuid.uuid4(),
                        "doc": doc_id,
                        "tid": doc.tenant_id,
                        "scope": doc.scope,
                        "ord": chunk.ordinal,
                        "page": chunk.page,
                        "section": chunk.section[:200],
                        "content": chunk.content,
                        "emb": _vector_literal(vec),
                        "model": self.embedder.model,
                        "tokens": chunk.token_estimate,
                        "flag": flag,
                    },
                )
            mpns = list(dict.fromkeys([*extra_mpns, *extract_part_numbers(extracted.text)]))
            for mpn in mpns:
                await conn.execute(
                    text(
                        """INSERT INTO kb.parts (id, tenant_id, scope, document_id, mpn,
                             manufacturer, source)
                           VALUES (:id, :tid, :scope, :doc, :mpn, :mfr, 'datasheet')"""
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": doc.tenant_id,
                        "scope": doc.scope,
                        "doc": doc_id,
                        "mpn": mpn,
                        "mfr": manufacturer,
                    },
                )
            await conn.execute(
                text(
                    """UPDATE kb.documents SET status = 'indexed', indexed_at = now(),
                         embedding_model = :model, error = NULL WHERE id = :id"""
                ),
                {"id": doc_id, "model": self.embedder.model},
            )
            span.set_attribute("kb.chunks", len(chunks))
            span.set_attribute("kb.suspicious_chunks", suspicious)
            if doc.scope == Scope.TENANT:
                await emit_audit(
                    conn,
                    AuditEvent(
                        action="kb.document.indexed",
                        object_type="kb_document",
                        object_id=str(doc_id),
                        after={
                            "chunks": len(chunks),
                            "parts": len(mpns),
                            "suspicious_chunks": suspicious,
                        },
                    ),
                )
        return IndexResult(doc_id, len(chunks), mpns, suspicious, list(extracted.limitations))

    async def mark_failed(self, conn: AsyncConnection, doc_id: uuid.UUID, error: str) -> None:
        await conn.execute(
            text("UPDATE kb.documents SET status = 'failed', error = :e WHERE id = :id"),
            {"id": doc_id, "e": error[:1000]},
        )

    async def supersede(self, conn: AsyncConnection, old_id: uuid.UUID, new_id: uuid.UUID) -> None:
        old = await self._document(conn, old_id)
        await conn.execute(
            text("UPDATE kb.documents SET superseded_at = now() WHERE id = :id"), {"id": old_id}
        )
        await conn.execute(
            text("UPDATE kb.documents SET supersedes = :old WHERE id = :new"),
            {"old": old_id, "new": new_id},
        )
        if old.scope == Scope.TENANT:
            await emit_audit(
                conn,
                AuditEvent(
                    action="kb.document.superseded",
                    object_type="kb_document",
                    object_id=str(old_id),
                    after={"superseded_by": str(new_id)},
                ),
            )

    # ------------------------------------------------------------------ corrections
    async def add_correction(
        self,
        conn: AsyncConnection,
        *,
        mpn: str,
        manufacturer: str,
        note: str,
        attributes: dict[str, str] | None = None,
    ) -> uuid.UUID:
        """A user's BOM correction becomes tenant knowledge (never global, ADR-0008)."""
        ctx = require_tenant()
        body = sanitize(
            f"Organisation-approved part {mpn} by {manufacturer}.\n"
            + "\n".join(f"{k}: {v}" for k, v in (attributes or {}).items())
            + (f"\nNote: {note}" if note else "")
        )
        data = body.encode()
        doc_id = await self.add_document(
            conn,
            DocumentMeta(
                title=f"Correction: {mpn}",
                mime_type="text/plain",
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                kind="correction",
                manufacturer=manufacturer,
            ),
            scope=Scope.TENANT,
            created_by=ctx.actor_id,
        )
        await self.index_document(
            conn,
            doc_id,
            ExtractedDocument([Page(1, body)], "text/plain"),
            extra_mpns=[mpn],
            manufacturer=manufacturer,
        )
        await conn.execute(
            text(
                "UPDATE kb.parts SET source = 'user_correction', created_by = :by,"
                " attributes = CAST(:attrs AS jsonb) WHERE document_id = :doc"
            ),
            {"by": ctx.actor_id, "doc": doc_id, "attrs": json.dumps(attributes or {})},
        )
        return doc_id

    # ------------------------------------------------------------------ retrieval
    async def snapshot(self, conn: AsyncConnection) -> str:
        """Freeze the set of active, indexed documents visible in this context."""
        ids = sorted(
            str(r)
            for r in (
                await conn.execute(
                    text(
                        "SELECT id FROM kb.documents WHERE status = 'indexed'"
                        " AND superseded_at IS NULL"
                    )
                )
            ).scalars()
        )
        ctx = current_tenant()
        tenant = ctx.tenant_id if ctx is not None else None
        digest = hashlib.sha256(
            f"{tenant}|{self.embedder.model}|{','.join(ids)}".encode()
        ).hexdigest()
        snap_id = f"kbs_{digest[:32]}"
        await conn.execute(
            text(
                """INSERT INTO kb.snapshots (id, tenant_id, scope, document_ids, embedding_model)
                   VALUES (:id, :tid, :scope, CAST(:ids AS uuid[]), :model)
                   ON CONFLICT (id) DO NOTHING"""
            ),
            {
                "id": snap_id,
                "tid": tenant,
                "scope": "tenant" if tenant else "global",
                "ids": "{" + ",".join(ids) + "}",
                "model": self.embedder.model,
            },
        )
        return snap_id

    async def _snapshot_docs(self, conn: AsyncConnection, snapshot_id: str) -> list[str]:
        row = (
            await conn.execute(
                text("SELECT document_ids FROM kb.snapshots WHERE id = :id"), {"id": snapshot_id}
            )
        ).first()
        if row is None:
            raise DocumentNotFoundError(f"snapshot {snapshot_id}")
        return [str(x) for x in row.document_ids]

    async def search(
        self,
        conn: AsyncConnection,
        query: str,
        *,
        k: int = 8,
        snapshot_id: str | None = None,
        kinds: Sequence[str] | None = None,
    ) -> list[Hit]:
        return (await self.search_many(conn, [query], k=k, snapshot_id=snapshot_id, kinds=kinds))[0]

    async def search_many(
        self,
        conn: AsyncConnection,
        queries: Sequence[str],
        *,
        k: int = 8,
        candidates: int = 40,
        snapshot_id: str | None = None,
        kinds: Sequence[str] | None = None,
    ) -> list[list[Hit]]:
        if not queries:
            return []
        doc_filter = await self._snapshot_docs(conn, snapshot_id) if snapshot_id else None
        with tracer.start_as_current_span(
            "kb.search", attributes={"kb.queries": len(queries), "kb.k": k}
        ):
            vectors = await self.embedder.embed(list(queries))
            await conn.execute(text(f"SET LOCAL hnsw.ef_search = {max(100, candidates * 2)}"))
            results: list[list[Hit]] = []
            for query, vec in zip(queries, vectors, strict=True):
                hits = await self._hybrid(conn, query, vec, candidates, doc_filter, kinds)
                results.append(self.reranker.rerank(query, hits)[:k])
        return results

    async def _hybrid(
        self,
        conn: AsyncConnection,
        query: str,
        vec: Sequence[float],
        candidates: int,
        doc_filter: list[str] | None,
        kinds: Sequence[str] | None,
    ) -> list[Hit]:
        where = ["d.status = 'indexed'"]
        params: dict[str, Any] = {"emb": _vector_literal(vec), "n": candidates}
        if doc_filter is not None:
            where.append("d.id = ANY(CAST(:docs AS uuid[]))")
            params["docs"] = "{" + ",".join(doc_filter) + "}"
        else:
            where.append("d.superseded_at IS NULL")
        if kinds:
            where.append("d.kind = ANY(CAST(:kinds AS text[]))")
            params["kinds"] = "{" + ",".join(kinds) + "}"
        cond = " AND ".join(where)
        cols = (
            "c.id, c.document_id, d.title, c.page, c.section, c.scope, c.content, d.kind,"
            " d.manufacturer, c.injection_suspect"
        )
        vec_rows = (
            await conn.execute(
                text(
                    f"""SELECT {cols} FROM kb.chunks c JOIN kb.documents d ON d.id = c.document_id
                        WHERE {cond}
                        ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT :n"""  # noqa: S608
                ),
                params,
            )
        ).all()
        tsq = _tsquery(query)
        fts_rows: list[Any] = []
        if tsq:
            fts_rows = list(
                (
                    await conn.execute(
                        text(
                            f"""SELECT {cols} FROM kb.chunks c
                                JOIN kb.documents d ON d.id = c.document_id,
                                to_tsquery('simple', :tsq) q
                                WHERE {cond} AND c.content_tsv @@ q
                                ORDER BY ts_rank_cd(c.content_tsv, q) DESC LIMIT :n"""  # noqa: S608
                        ),
                        params | {"tsq": tsq},
                    )
                ).all()
            )
        hits: dict[uuid.UUID, Hit] = {}
        for rank, row in enumerate(vec_rows, start=1):
            hits[row.id] = Hit(
                row.id,
                row.document_id,
                row.title,
                row.page,
                row.section,
                row.scope,
                row.content,
                row.kind,
                row.manufacturer,
                row.injection_suspect,
                1.0 / (RRF_K + rank),
                vector_rank=rank,
            )
        for rank, row in enumerate(fts_rows, start=1):
            hit = hits.get(row.id)
            if hit is None:
                hit = hits[row.id] = Hit(
                    row.id,
                    row.document_id,
                    row.title,
                    row.page,
                    row.section,
                    row.scope,
                    row.content,
                    row.kind,
                    row.manufacturer,
                    row.injection_suspect,
                    0.0,
                )
            hit.score += 1.0 / (RRF_K + rank)
            hit.text_rank = rank
        return sorted(hits.values(), key=lambda h: -h.score)

    # ------------------------------------------------------------------ parts catalogue
    async def known_mpns(self, conn: AsyncConnection) -> set[str]:
        rows = await conn.execute(text("SELECT DISTINCT mpn_norm FROM kb.parts"))
        return {str(r) for r in rows.scalars()}

    async def find_parts(
        self, conn: AsyncConnection, mpn_prefix: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        norm = re.sub(r"\s+", "", mpn_prefix).upper()
        rows = await conn.execute(
            text(
                """SELECT p.mpn, p.manufacturer, p.scope, p.source, p.document_id, p.attributes
                   FROM kb.parts p WHERE p.mpn_norm LIKE :prefix ESCAPE '\\'
                   ORDER BY (p.source = 'user_correction') DESC, p.mpn LIMIT :limit"""
            ),
            {
                "prefix": norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
                "limit": limit,
            },
        )
        return [dict(r._mapping) for r in rows]
