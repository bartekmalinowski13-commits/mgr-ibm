"""Knowledge-base helpers for tests: index the synthetic datasheet corpus."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import platform_transaction
from bomagent_kb import DocumentMeta, KnowledgeBase, Scope, extract
from bomagent_llm.embeddings import HashingEmbeddings
from bomagent_testing.data import FIXTURES

DATASHEETS = FIXTURES / "datasheets"
QUERIES = FIXTURES / "kb" / "queries.yaml"


def make_kb() -> KnowledgeBase:
    return KnowledgeBase(HashingEmbeddings())


def load_queries() -> list[dict[str, str]]:
    return list(yaml.safe_load(QUERIES.read_text())["queries"])


async def index_global_corpus(
    platform_engine: AsyncEngine, kb: KnowledgeBase, paths: list[Path] | None = None
) -> dict[str, uuid.UUID]:
    """Index datasheets into the global scope (platform role); returns stem -> doc id."""
    ids: dict[str, uuid.UUID] = {}
    for path in paths or sorted(DATASHEETS.glob("*.md")):
        data = path.read_bytes()
        async with platform_transaction(platform_engine) as conn:
            doc_id = await kb.add_document(
                conn,
                DocumentMeta(
                    title=path.stem,
                    mime_type="text/markdown",
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    source_uri=f"fixture://{path.name}",
                ),
                scope=Scope.GLOBAL,
                created_by="platform-pipeline",
            )
            await kb.index_document(conn, doc_id, extract(path.name, data))
        ids[path.stem] = doc_id
    return ids
