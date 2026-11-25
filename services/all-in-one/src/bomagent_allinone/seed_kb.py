"""The platform pipeline for the global knowledge-base corpus of a pilot (ADR-0008).

``python -m bomagent_allinone seed-kb`` loads the sample datasheets
(``bomagent_api.samples.catalog.sample_datasheets``) into the ``global`` scope with the
platform role, so every organisation, including the ones created later, can cite them.
Idempotent: a document whose content is already indexed is left alone, one left
``pending``/``failed`` by an interrupted run is indexed again. Text is extracted in the
same resource-limited sandbox as customer uploads, and embedded with the configured
gateway model (the fake embeddings are refused outside local/test: they would mix
incompatible vectors into a shared corpus).
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.samples.catalog import SampleDatasheet
from bomagent_common.db import platform_transaction
from bomagent_common.logging import get_logger
from bomagent_kb import DocumentMeta, ExtractedDocument, KnowledgeBase, Scope
from bomagent_kb_indexer.sandbox import extract_sandboxed

log = get_logger(__name__)

CREATED_BY = "platform-pipeline"
Extractor = Callable[..., ExtractedDocument]


@dataclass
class SeedReport:
    indexed: int = 0
    unchanged: int = 0


async def seed_global_corpus(
    platform_engine: AsyncEngine,
    kb: KnowledgeBase,
    datasheets: Sequence[SampleDatasheet],
    *,
    extractor: Extractor = extract_sandboxed,
) -> SeedReport:
    report = SeedReport()
    for sheet in datasheets:
        data = sheet.path.read_bytes()
        meta = DocumentMeta(
            title=sheet.path.stem,
            kind="datasheet",
            manufacturer=sheet.manufacturer,
            mime_type="text/markdown",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            source_uri=f"sample://datasheets/{sheet.path.name}",
        )
        async with platform_transaction(platform_engine) as conn:
            doc_id, _created = await kb.register_document(
                conn, meta, scope=Scope.GLOBAL, created_by=CREATED_BY
            )
            status = (
                await conn.execute(
                    text("SELECT status FROM kb.documents WHERE id = :id"), {"id": doc_id}
                )
            ).scalar()
        if status == "indexed":
            report.unchanged += 1
            continue
        extracted = await asyncio.to_thread(extractor, sheet.path.name, data)
        async with platform_transaction(platform_engine) as conn:
            result = await kb.index_document(
                conn, doc_id, extracted, manufacturer=sheet.manufacturer
            )
        log.info("kb_global_seeded", document=sheet.path.name, chunks=result.chunks)
        report.indexed += 1
    return report


def run() -> None:
    """``seed-kb``: the sample datasheets into the global corpus of this deployment."""
    from bomagent_allinone.app import Settings, _llm
    from bomagent_api.samples.catalog import sample_datasheets
    from bomagent_common.db import make_engine
    from bomagent_llm.embeddings import HashingEmbeddings

    settings = Settings()
    if not settings.platform_database_url:
        raise SystemExit("seed-kb needs the platform role (BOMAGENT_PLATFORM_DATABASE_URL)")
    _chat, embedder = _llm(settings)
    if isinstance(embedder, HashingEmbeddings) and settings.environment not in {"local", "test"}:
        raise SystemExit("seed-kb refuses the fake embeddings outside local/test")

    async def main() -> Any:
        engine = make_engine(settings.platform_database_url or "", pool_size=1)
        try:
            return await seed_global_corpus(engine, KnowledgeBase(embedder), sample_datasheets())
        finally:
            await engine.dispose()

    report = asyncio.run(main())
    log.info("kb_global_seed_done", indexed=report.indexed, unchanged=report.unchanged)
    sys.stdout.write(
        f"global corpus: {report.indexed} indexed, {report.unchanged} already indexed\n"
    )
