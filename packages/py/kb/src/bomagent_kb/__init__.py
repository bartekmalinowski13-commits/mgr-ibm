"""Knowledge base: ingestion, chunking, hybrid retrieval (pgvector + FTS), scopes."""

from bomagent_kb.extract import ExtractedDocument, ExtractionError, Page, extract
from bomagent_kb.store import (
    DocumentMeta,
    DocumentNotFoundError,
    Hit,
    IndexResult,
    KnowledgeBase,
    LexicalReranker,
    Scope,
)

__version__ = "0.1.0"
__all__ = [
    "DocumentMeta",
    "DocumentNotFoundError",
    "ExtractedDocument",
    "ExtractionError",
    "Hit",
    "IndexResult",
    "KnowledgeBase",
    "LexicalReranker",
    "Page",
    "Scope",
    "extract",
]
