"""Knowledge-base access for agents.

``KbRetriever`` wraps :class:`bomagent_kb.KnowledgeBase` and opens a **short tenant
transaction per call** (RLS: the tenant sees its own space + the global corpus), so a run
never holds a database connection while waiting for an LLM. ``StaticRetriever`` serves a
folder of markdown/text datasheets from memory (CLI, tests, offline experiments).
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_bom.model import KbCitation
from bomagent_common.db import tenant_transaction
from bomagent_kb import KnowledgeBase
from bomagent_kb.chunking import chunk_document
from bomagent_kb.extract import ExtractedDocument, Page
from bomagent_kb.parts import extract_part_numbers
from bomagent_kb.safety import looks_like_injection, sanitize


@dataclass(frozen=True)
class Excerpt:
    chunk_id: str
    document_id: str
    title: str
    content: str
    page: int | None = None
    scope: str = "global"
    score: float = 0.0

    def citation(self, quote_chars: int = 300) -> KbCitation:
        return KbCitation(
            document_id=self.document_id,
            chunk_id=self.chunk_id,
            page=self.page,
            scope="tenant" if self.scope == "tenant" else "global",
            quote=self.content[:quote_chars],
        )


class Retriever(Protocol):
    async def search_many(self, queries: Sequence[str], k: int) -> list[list[Excerpt]]: ...

    async def known_mpns(self) -> set[str]: ...


def norm_mpn(mpn: str) -> str:
    return re.sub(r"\s+", "", mpn).upper()


class KbRetriever:
    def __init__(
        self,
        kb: KnowledgeBase,
        engine: AsyncEngine,
        tenant_id: uuid.UUID,
        *,
        snapshot_id: str | None = None,
    ) -> None:
        self.kb = kb
        self.engine = engine
        self.tenant_id = tenant_id
        self.snapshot_id = snapshot_id

    async def search_many(self, queries: Sequence[str], k: int) -> list[list[Excerpt]]:
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            results = await self.kb.search_many(
                conn, list(queries), k=k, snapshot_id=self.snapshot_id
            )
        return [
            [
                Excerpt(
                    chunk_id=str(h.chunk_id),
                    document_id=str(h.document_id),
                    title=h.title,
                    content=h.content,
                    page=h.page,
                    scope=h.scope,
                    score=h.score,
                )
                for h in hits
                if not h.injection_suspect
            ]
            for hits in results
        ]

    async def known_mpns(self) -> set[str]:
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            return await self.kb.known_mpns(conn)


_WORD = re.compile(r"[a-z0-9µΩ]+(?:\.[0-9]+)?", re.IGNORECASE)


class StaticRetriever:
    """Lexical retrieval over local files (no database, deterministic)."""

    def __init__(self, documents: dict[str, str]) -> None:
        self._chunks: list[Excerpt] = []
        self._mpns: set[str] = set()
        for name, text in sorted(documents.items()):
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"static:{name}"))
            self._mpns |= {norm_mpn(p) for p in extract_part_numbers(text)}
            doc = ExtractedDocument([Page(1, sanitize(text))], "text/markdown")
            for chunk in chunk_document(doc):
                if looks_like_injection(chunk.content):
                    continue  # same policy as KbRetriever: suspicious chunks never reach agents
                self._chunks.append(
                    Excerpt(
                        chunk_id=f"{name}#{chunk.ordinal}",
                        document_id=doc_id,
                        title=name,
                        content=chunk.content,
                        page=chunk.page,
                    )
                )

    @classmethod
    def from_directory(cls, directory: str | Path) -> StaticRetriever:
        root = Path(directory)
        docs = {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(root.iterdir())
            if p.suffix.lower() in {".md", ".txt"}
        }
        return cls(docs)

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {t.lower() for t in _WORD.findall(text)}

    def _index(self) -> list[set[str]]:
        if not hasattr(self, "_terms_cache"):
            self._terms_cache = [self._terms(c.content + " " + c.title) for c in self._chunks]
            n = len(self._chunks)
            df: dict[str, int] = {}
            for terms in self._terms_cache:
                for t in terms:
                    df[t] = df.get(t, 0) + 1
            self._idf = {t: math.log(1 + n / d) for t, d in df.items()}
        return self._terms_cache

    async def search_many(self, queries: Sequence[str], k: int) -> list[list[Excerpt]]:
        out: list[list[Excerpt]] = []
        index = self._index()
        for q in queries:
            terms = self._terms(q)
            scored = []
            for c, chunk_terms in zip(self._chunks, index, strict=True):
                overlap = sum(self._idf[t] for t in terms & chunk_terms)
                if overlap:
                    scored.append((round(overlap, 6), c.chunk_id, c))
            scored.sort(key=lambda t: (-t[0], t[1]))
            out.append([Excerpt(**{**c.__dict__, "score": float(s)}) for s, _, c in scored[:k]])
        return out

    async def known_mpns(self) -> set[str]:
        return set(self._mpns)
