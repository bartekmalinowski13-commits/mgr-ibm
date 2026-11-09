"""Text extraction from knowledge-base documents.

* PDF: ``pypdf`` (BSD) - text layer per page. Scanned PDFs without a text layer yield
  empty pages and the document is marked with a limitation (OCR is a Docling feature).
* Docling (MIT) - used when installed and enabled (``kb-indexer`` image, extra
  ``bomagent-kb[docling]``); better tables/layout, OCR. Not required for tests.
* Plain text / Markdown.

PyMuPDF is intentionally not used: AGPL-3.0 is incompatible with a closed SaaS without a
commercial licence (see docs/DECISIONS_LOG.md).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from bomagent_kb.safety import sanitize

MAX_PAGES = 2000


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class Page:
    number: int  # 1-based
    text: str


@dataclass
class ExtractedDocument:
    pages: list[Page]
    mime_type: str
    limitations: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def mime_for(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }.get(suffix, "application/octet-stream")


def _pdf(data: bytes) -> ExtractedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("encrypted PDF")
        if len(reader.pages) > MAX_PAGES:
            raise ExtractionError(f"PDF has more than {MAX_PAGES} pages")
        pages = [
            Page(i + 1, sanitize(page.extract_text() or "")) for i, page in enumerate(reader.pages)
        ]
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"unreadable PDF: {type(exc).__name__}") from exc
    doc = ExtractedDocument(pages, "application/pdf")
    empty = sum(1 for p in pages if not p.text.strip())
    if empty:
        doc.limitations.append(f"{empty} page(s) without a text layer (OCR needed)")
    return doc


def extract(name: str, data: bytes, *, use_docling: bool = False) -> ExtractedDocument:
    mime = mime_for(name)
    if mime == "application/pdf":
        if use_docling:  # pragma: no cover - optional heavy dependency
            from bomagent_kb.docling_extract import extract_with_docling

            return extract_with_docling(data)
        return _pdf(data)
    if mime in {"text/plain", "text/markdown"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("text file is not UTF-8") from exc
        # form feed separates pages in plain-text exports
        pages = [Page(i + 1, sanitize(t)) for i, t in enumerate(text.split("\f"))]
        return ExtractedDocument(pages, mime)
    raise ExtractionError(f"unsupported knowledge-base file type: {name}")
