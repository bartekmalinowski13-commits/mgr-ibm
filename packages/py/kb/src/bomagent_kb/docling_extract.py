"""Optional Docling-based PDF extraction (installed in the kb-indexer image)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bomagent_kb.extract import ExtractedDocument, Page
from bomagent_kb.safety import sanitize


def extract_with_docling(data: bytes) -> ExtractedDocument:  # pragma: no cover - heavy
    from docling.document_converter import DocumentConverter

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(data)
        result = DocumentConverter().convert(str(path))
    doc = result.document
    pages: dict[int, list[str]] = {}
    for item, _level in doc.iterate_items():
        prov = getattr(item, "prov", None) or []
        page_no = prov[0].page_no if prov else 1
        text = getattr(item, "text", "") or ""
        if hasattr(item, "export_to_markdown") and not text:
            text = item.export_to_markdown(doc)
        if text:
            pages.setdefault(page_no, []).append(text)
    return ExtractedDocument(
        [Page(n, sanitize("\n".join(t))) for n, t in sorted(pages.items())], "application/pdf"
    )
