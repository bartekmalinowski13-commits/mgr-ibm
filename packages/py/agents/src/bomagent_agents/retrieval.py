"""Knowledge retrieval for agents: database-backed (production) or in-memory (CLI, tests).

Both return ``Evidence``: the KB hits plus MPN candidates found in them, so the MPN agent
chooses from evidence instead of recalling part numbers (anti-hallucination)."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import tenant_transaction
from bomagent_kb import Hit, extract
from bomagent_kb.chunking import chunk_document
from bomagent_kb.parts import extract_part_numbers
from bomagent_kb.safety import looks_like_injection
from bomagent_kb.store import KnowledgeBase, LexicalReranker
from bomagent_llm.embeddings import HashingEmbeddings

_ORDERING = re.compile(r"order|part number|mpn", re.IGNORECASE)


@dataclass
class Candidate:
    mpn: str
    context: str
    chunk_id: str
    document: str


@dataclass
class Evidence:
    hits: list[Hit]
    candidates: list[Candidate] = field(default_factory=list)


def candidates_from(hits: list[Hit]) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for h in hits:
        if h.injection_suspect:
            continue
        in_ordering = bool(_ORDERING.search(h.section))
        for line in h.content.splitlines():
            text = f"part number {line}" if in_ordering else line
            for mpn in extract_part_numbers(text):
                if mpn not in seen and mpn in line:
                    seen.add(mpn)
                    out.append(Candidate(mpn, line.strip()[:240], str(h.chunk_id), h.title))
    return out


class Retriever(Protocol):
    async def evidence(self, queries: list[str], k: int) -> list[Evidence]: ...

    async def known_mpns(self) -> set[str]: ...


class InMemoryRetriever:
    """Small in-process index (hashing embeddings + lexical rerank) over a directory of
    text/Markdown/PDF datasheets - for the CLI and tests, no database required."""

    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits
        self._emb = HashingEmbeddings()
        self._vectors: list[list[float]] = []
        self._reranker = LexicalReranker()

    @classmethod
    async def from_directory(cls, directory: str | Path) -> InMemoryRetriever:
        hits: list[Hit] = []
        for path in sorted(Path(directory).iterdir()):  # noqa: ASYNC240 - startup, small dir
            if path.suffix.lower() not in {".md", ".txt", ".pdf"}:
                continue
            doc_id = uuid.uuid5(uuid.NAMESPACE_URL, path.name)
            for chunk in chunk_document(extract(path.name, path.read_bytes())):
                hits.append(
                    Hit(
                        uuid.uuid5(doc_id, str(chunk.ordinal)),
                        doc_id,
                        path.stem,
                        chunk.page,
                        chunk.section,
                        "global",
                        chunk.content,
                        "datasheet",
                        "",
                        looks_like_injection(chunk.content),
                    )
                )
        index = cls(hits)
        index._vectors = await index._emb.embed([h.content for h in hits])
        return index

    async def evidence(self, queries: list[str], k: int) -> list[Evidence]:
        qvecs = await self._emb.embed(queries)
        out: list[Evidence] = []
        for query, qv in zip(queries, qvecs, strict=True):
            scored = sorted(
                range(len(self._hits)),
                key=lambda i: -sum(a * b for a, b in zip(qv, self._vectors[i], strict=True)),
            )[: max(20, k)]
            hits = []
            for rank, i in enumerate(scored, start=1):
                h = self._hits[i]
                hits.append(
                    Hit(
                        h.chunk_id,
                        h.document_id,
                        h.title,
                        h.page,
                        h.section,
                        h.scope,
                        h.content,
                        h.kind,
                        h.manufacturer,
                        h.injection_suspect,
                        1.0 / (60 + rank),
                        vector_rank=rank,
                    )
                )
            top = self._reranker.rerank(query, hits)[:k]
            out.append(Evidence(top, candidates_from(top)))
        return out

    async def known_mpns(self) -> set[str]:
        return {c.mpn.upper() for c in candidates_from(self._hits)}

    def __len__(self) -> int:
        return len(self._hits)


class KbRetriever:
    """Production retriever: tenant-scoped hybrid search in PostgreSQL (RLS applies)."""

    def __init__(
        self,
        kb: KnowledgeBase,
        engine: AsyncEngine,
        tenant_id: uuid.UUID,
        snapshot_id: str | None = None,
    ) -> None:
        self._kb, self._engine, self._tenant, self._snapshot = kb, engine, tenant_id, snapshot_id

    async def evidence(self, queries: list[str], k: int) -> list[Evidence]:
        async with tenant_transaction(self._engine, self._tenant) as conn:
            results = await self._kb.search_many(conn, queries, k=k, snapshot_id=self._snapshot)
        return [Evidence(hits, candidates_from(hits)) for hits in results]

    async def known_mpns(self) -> set[str]:
        async with tenant_transaction(self._engine, self._tenant) as conn:
            return await self._kb.known_mpns(conn)


def cosine(a: list[float], b: list[float]) -> float:  # pragma: no cover - helper
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)
