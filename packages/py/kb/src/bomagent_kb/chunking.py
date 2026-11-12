"""Page- and heading-aware chunking.

Chunks never cross pages (citations point to a page) and start a new chunk at headings,
so a chunk usually covers one topic ("Ordering information", "Absolute maximum
ratings"). Size is bounded in estimated tokens (~4 characters per token for datasheets),
with a small word overlap between consecutive chunks of one section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bomagent_kb.extract import ExtractedDocument

_HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 /&()\-]{3,60}|\d+(\.\d+)*\s+[A-Z].{2,60})$")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int
    section: str
    content: str

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.content) // 4)


def _blocks(text: str) -> list[tuple[str, str]]:
    """(section, paragraph) pairs."""
    section = ""
    out: list[tuple[str, str]] = []
    para: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if para:
                out.append((section, " ".join(para)))
                para = []
            continue
        if _HEADING.match(line) and len(line) < 80:
            if para:
                out.append((section, " ".join(para)))
                para = []
            section = line.lstrip("#").strip()
            continue
        para.append(line)
    if para:
        out.append((section, " ".join(para)))
    return out


def _emit(chunks: list[Chunk], page: int, section: str, buf: list[str]) -> None:
    body = "\n".join(b for b in buf if b.strip())
    if body:
        content = f"{section}\n{body}" if section else body
        chunks.append(Chunk(len(chunks), page, section, content))


def chunk_document(
    doc: ExtractedDocument, *, max_tokens: int = 350, overlap_words: int = 30
) -> list[Chunk]:
    max_chars = max_tokens * 4
    chunks: list[Chunk] = []
    for page in doc.pages:
        buf: list[str] = []
        buf_section = ""
        for section, para in _blocks(page.text):
            pieces = [para[i : i + max_chars] for i in range(0, len(para), max_chars)]
            for piece in pieces:
                size = sum(len(b) for b in buf)
                if buf and (section != buf_section or size + len(piece) > max_chars):
                    tail = " ".join(" ".join(buf).split()[-overlap_words:])
                    _emit(chunks, page.number, buf_section, buf)
                    buf = [tail] if section == buf_section and tail else []
                buf_section = section
                buf.append(piece)
        _emit(chunks, page.number, buf_section, buf)
    return chunks
