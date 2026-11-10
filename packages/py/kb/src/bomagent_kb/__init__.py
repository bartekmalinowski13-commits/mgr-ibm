"""Knowledge base: ingestion, chunking, hybrid retrieval (pgvector + FTS), scopes."""

from bomagent_kb.documents import get_document, list_documents, register_document
from bomagent_kb.extract import ExtractedDocument, ExtractionError, Page, extract
from bomagent_kb.store import (
    DocumentNotFoundError,
    Hit,
    IndexResult,
    KnowledgeBase,
    LexicalReranker,
)
from bomagent_kb.store_types import DocumentMeta, Scope

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
    "get_document",
    "list_documents",
    "register_document",
]
