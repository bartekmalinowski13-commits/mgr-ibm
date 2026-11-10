"""BOM tables in PDF (printed BOM reports of EDA tools, customer BOMs).

Text is taken with its position on the page (``pypdf`` text visitor) instead of a
plain-text rendering: in printed tables long cells run into their neighbours, so
splitting lines on spaces would glue columns together. A header row is found by the
same column names as the CSV import; every text fragment below it is assigned to the
column whose header starts left of it, fragments of one column are joined, and a line
without a designator continues the previous row (wrapped cells). Repeated headers on
later pages are skipped.

Reading a layout is a heuristic, so the result has lower confidence and asks for
review (FORMATS.md). PDFs without a text layer (scans) are reported - OCR is not part
of v1. Encrypted PDFs are refused.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from bomagent_bom.dnp import parse_dnp
from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError
from bomagent_cad.csv_bom import ALIASES, expand_refdes

MAX_PAGES = 100
MAX_COMPONENTS = 100_000


@dataclass(frozen=True)
class _Chunk:
    x: float
    y: float
    size: float
    text: str


def _column(text: str) -> str | None:
    key = text.strip().casefold()
    for column, aliases in ALIASES.items():
        if key in aliases:
            return column
    return None


class PdfBomParser:
    format_id = "pdf-bom"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix != ".pdf" or not file.data.startswith(b"%PDF"):
            return 0.0
        return 0.7  # a PDF may also be a schematic or a datasheet: parse decides

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        candidates = [f for f in files if self.sniff(f) > 0.5]
        if len(candidates) != 1:
            raise ParseError("expected exactly one PDF BOM", code="pdf.count")
        file = candidates[0]
        pages = self._pages(file)
        if not any(pages):
            raise ParseError(
                f"{file.name}: the PDF has no text layer (scanned?) - OCR is not supported"
                " yet; export the BOM as CSV",
                code="pdf.no_text",
            )
        limitations = ["BOM read from the PDF page layout - review the items"]
        components = self._read_table(file, pages, limitations)
        confidence = max(0.5, 0.75 - 0.02 * (len(limitations) - 1))
        return ParsedDesign(
            design_name=file.name.rsplit(".", 1)[0],
            source_format=self.format_id,
            components=components,
            confidence=confidence,
            limitations=limitations,
            files=[f.source() for f in files],
            parser_version=self.version,
        )

    @staticmethod
    def _pages(file: FileRef) -> list[list[_Chunk]]:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        errors = (PyPdfError, ValueError, KeyError, TypeError, AttributeError)
        try:
            reader = PdfReader(io.BytesIO(file.data), strict=False)
            encrypted, page_count = reader.is_encrypted, len(reader.pages)
        except errors as exc:
            raise ParseError(
                f"{file.name}: not a readable PDF ({exc})", code="pdf.malformed"
            ) from exc
        if encrypted:
            raise ParseError(f"{file.name}: encrypted PDF", code="pdf.encrypted")
        if page_count > MAX_PAGES:
            raise ParseError(f"{file.name}: more than {MAX_PAGES} pages", code="file.too_large")
        out: list[list[_Chunk]] = []
        for page in reader.pages:
            chunks: list[_Chunk] = []

            def visit(
                text: str,
                cm: list[float],
                tm: list[float],
                _font: object,
                size: float,
                chunks: list[_Chunk] = chunks,
            ) -> None:
                if not text.strip():
                    return
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                chunks.append(_Chunk(x, y, float(size or 8.0), text.strip()))

            try:
                page.extract_text(visitor_text=visit)
            except errors as exc:
                raise ParseError(
                    f"{file.name}: not a readable PDF ({exc})", code="pdf.malformed"
                ) from exc
            out.append(chunks)
        return out

    @staticmethod
    def _lines(chunks: list[_Chunk]) -> list[list[_Chunk]]:
        """Chunks grouped into text lines, top of the page first."""
        lines: list[list[_Chunk]] = []
        for c in sorted(chunks, key=lambda c: (-c.y, c.x)):
            if lines and abs(lines[-1][0].y - c.y) <= 0.5 * max(c.size, lines[-1][0].size):
                lines[-1].append(c)
            else:
                lines.append([c])
        return [sorted(line, key=lambda c: c.x) for line in lines]

    def _read_table(
        self, file: FileRef, pages: list[list[_Chunk]], limitations: list[str]
    ) -> list[Component]:
        header: list[tuple[float, str]] | None = None
        rows: list[dict[str, str]] = []
        for chunks in pages:
            for line in self._lines(chunks):
                named = [(c.x, _column(c.text)) for c in line]
                found = {name for _, name in named if name}
                if "refdes" in found and ({"value", "mpn"} & found):
                    header = [(x, name) for x, name in named if name]  # repeated: re-anchored
                    tolerance = max(c.size for c in line)
                    continue
                if header is None:
                    continue
                row: dict[str, list[str]] = {}
                for c in line:
                    column = None
                    for x, name in header:
                        if c.x + tolerance >= x:
                            column = name
                    if column:
                        row.setdefault(column, []).append(c.text)
                cells = {k: " ".join(v) for k, v in row.items()}
                if "refdes" in cells:
                    rows.append(cells)
                elif rows and cells:  # wrapped cell: continues the previous row
                    for k, v in cells.items():
                        rows[-1][k] = f"{rows[-1].get(k, '')} {v}".strip()
        if header is None or not rows:
            raise ParseError(
                f"{file.name}: no BOM table found (expected a header with e.g. 'Designator'"
                " and 'Value' or 'MPN')",
                code="pdf.no_bom_table",
            )
        components: list[Component] = []
        seen: set[str] = set()
        for cells in rows:
            refs = expand_refdes(cells["refdes"])
            qty = cells.get("quantity", "").strip()
            if qty.isdigit() and int(qty) != len(refs):
                limitations.append(f"{cells['refdes']}: quantity {qty} but {len(refs)} designators")
            fields = {
                key: cells[column]
                for key, column in (
                    ("MPN", "mpn"),
                    ("Manufacturer", "manufacturer"),
                    ("Description", "description"),
                )
                if cells.get(column)
            }
            dnp = bool(parse_dnp(cells.get("dnp", ""), "dnp")) if cells.get("dnp") else False
            for ref in refs:
                if ref in seen:
                    limitations.append(f"{ref} listed more than once")
                    continue
                seen.add(ref)
                try:
                    components.append(
                        Component(
                            refdes=ref,
                            value=cells.get("value", ""),
                            footprint=cells.get("footprint", ""),
                            fields=dict(fields),
                            dnp=dnp,
                        )
                    )
                except ValueError:
                    limitations.append(f"{ref!r} is not a designator - skipped")
            if len(components) > MAX_COMPONENTS:
                raise ParseError(f"{file.name}: too many components", code="file.too_large")
        return components
