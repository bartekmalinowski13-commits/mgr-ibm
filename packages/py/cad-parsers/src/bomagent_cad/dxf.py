"""DXF drawings - mechanical parts lists (enclosure, fasteners, labels).

Read with ``ezdxf``'s recovery loader (ASCII and binary DXF, tolerant of damaged files),
from memory only. Two encodings of a parts list are recognised:

1. **Block attributes** - one ``INSERT`` per row whose attributes carry the columns
   (``POS``, ``PART_NO``, ``DESCRIPTION``, ``QTY``, ...); the most reliable form.
2. **Exploded table** - ``TEXT``/``MTEXT`` laid out in a grid: a header row is found by
   column names, cells are assigned to the column whose header starts left of them.
   Layout heuristics, so confidence is lower and the result says so.

Every row becomes mechanical parts ``MP<pos>``; a quantity N > 1 becomes N designators
(``MP2A`` ... ``MP2D``) so the BOM quantity equals the designator count. Drawings carry
no PCB footprints - reported as a limitation. ``ACAD_TABLE`` objects are not read (an
exploded copy is).
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from dataclasses import dataclass

from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError

MAX_QUANTITY = 1000
MAX_COMPONENTS = 100_000
_ITEM = re.compile(r"^\d{1,5}$")
_QTY = re.compile(r"^(\d{1,9})(?:[.,]0+)?(?:\s*(?:pcs|pc|szt|x)\.?)?$", re.IGNORECASE)
COLUMNS: dict[str, set[str]] = {
    "item": {"pos", "position", "item", "itemno", "no", "nr", "poz", "lp", "find", "findno"},
    "mpn": {
        "partnumber",
        "partno",
        "pn",
        "mpn",
        "part",
        "catalognumber",
        "catalogno",
        "ordercode",
        "orderno",
        "nrkatalogowy",
        "numer",
        "drawingno",
        "partnum",
    },
    "description": {"description", "desc", "name", "title", "nazwa", "opis", "designation"},
    "quantity": {"qty", "quantity", "count", "ilosc", "ilość", "szt", "pcs"},
    "material": {"material", "materiał", "mat"},
    "manufacturer": {"manufacturer", "mfr", "vendor", "producent", "supplier"},
}


def _column(name: str) -> str | None:
    key = re.sub(r"[^0-9a-ząćęłńóśźż]", "", name.casefold())
    for column, aliases in COLUMNS.items():
        if key in aliases:
            return column
    return None


def _suffix(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    out = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


@dataclass(frozen=True)
class _Text:
    x: float
    y: float
    height: float
    text: str


class DxfParser:
    format_id = "dxf"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix != ".dxf":
            return 0.0
        head = file.data[:2048]
        if head.startswith(b"AutoCAD Binary DXF") or b"SECTION" in head:
            return 0.9
        return 0.0

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        candidates = [f for f in files if self.sniff(f) > 0.5]
        if len(candidates) != 1:
            raise ParseError("expected exactly one DXF drawing", code="dxf.count")
        file = candidates[0]
        doc = self._load(file)
        limitations = ["mechanical parts list from a drawing: no PCB footprints"]
        rows = self._attribute_rows(doc)
        confidence = 0.9
        if not rows:
            rows = self._table_rows(doc)
            confidence = 0.75
            if rows:
                limitations.append(
                    "parts list read from text layout (exploded table) - check the columns"
                )
        if not rows:
            hint = (
                " (ACAD_TABLE objects are not read - explode the table first)"
                if any(True for _ in doc.modelspace().query("ACAD_TABLE"))
                else ""
            )
            raise ParseError(f"{file.name}: no parts list found{hint}", code="dxf.no_parts_list")
        components = self._components(rows, limitations)
        if len(limitations) > 2:
            confidence = max(0.5, confidence - 0.05 * (len(limitations) - 2))
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
    def _load(file: FileRef):  # type: ignore[no-untyped-def]  # ezdxf Drawing
        from ezdxf import recover
        from ezdxf.lldxf.const import DXFError

        try:
            doc, _auditor = recover.read(io.BytesIO(file.data))
        except (DXFError, ValueError, UnicodeDecodeError, IndexError) as exc:
            raise ParseError(
                f"{file.name}: not a readable DXF ({exc})", code="dxf.malformed"
            ) from exc
        return doc

    @staticmethod
    def _attribute_rows(doc) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
        """Rows from block attributes. A block is a parts-list row only if it is used at
        least twice or carries a part number / quantity: a single title block (with
        NO / TITLE tags) must not pass for a one-line parts list."""
        by_block: dict[str, list[dict[str, str]]] = {}
        for layout in doc.layouts:
            for insert in layout.query("INSERT"):
                row: dict[str, str] = {}
                for attrib in insert.attribs:
                    column = _column(attrib.dxf.tag)
                    if column and attrib.dxf.text.strip():
                        row.setdefault(column, attrib.dxf.text.strip())
                if "item" in row and ({"mpn", "description"} & row.keys()):
                    by_block.setdefault(insert.dxf.name, []).append(row)
        rows: list[dict[str, str]] = []
        for block_rows in by_block.values():
            if len(block_rows) >= 2 or any({"mpn", "quantity"} & r.keys() for r in block_rows):
                rows += block_rows
        return rows

    @staticmethod
    def _texts(layout) -> Iterable[_Text]:  # type: ignore[no-untyped-def]
        for e in layout.query("TEXT MTEXT"):
            if e.dxftype() == "TEXT":
                text, height = e.dxf.text, e.dxf.get("height", 2.5)
            else:
                text, height = e.plain_text(), e.dxf.get("char_height", 2.5)
            if text and text.strip():
                ins = e.dxf.insert
                yield _Text(float(ins.x), float(ins.y), float(height or 2.5), text.strip())

    def _table_rows(self, doc) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
        rows: list[dict[str, str]] = []
        for layout in doc.layouts:
            texts = sorted(self._texts(layout), key=lambda t: (t.y, t.x))
            lines: list[list[_Text]] = []
            for t in texts:
                if lines and abs(lines[-1][0].y - t.y) <= 0.6 * max(t.height, lines[-1][0].height):
                    lines[-1].append(t)
                else:
                    lines.append([t])
            header = None
            for line in lines:
                cols = [(t.x, _column(t.text)) for t in sorted(line, key=lambda t: t.x)]
                named = [(x, c) for x, c in cols if c]
                found = {c for _, c in named}
                if "item" in found and ({"mpn", "description"} & found) and len(named) >= 2:
                    header = (line, named)
                    break
            if header is None:
                continue
            header_line, columns = header
            tolerance = max(t.height for t in header_line)
            left = min(x for x, _ in columns) - tolerance
            h = lines.index(header_line)
            # only lines next to the header (rows go up or down from it, both occur in
            # practice); the first gap or non-row line ends the table in that direction
            for direction in (1, -1):
                prev_y = header_line[0].y
                i = h + direction
                while 0 <= i < len(lines):
                    line = lines[i]
                    if abs(line[0].y - prev_y) > 3.5 * tolerance:
                        break
                    row: dict[str, str] = {}
                    for t in line:
                        if t.x < left:
                            continue
                        column = None
                        for x, name in columns:
                            if t.x + tolerance >= x:
                                column = name
                        if column:
                            row.setdefault(column, t.text)
                    if not (
                        _ITEM.match(row.get("item", "")) and ({"mpn", "description"} & row.keys())
                    ):
                        break
                    rows.append(row)
                    prev_y = line[0].y
                    i += direction
        return rows

    @staticmethod
    def _components(rows: list[dict[str, str]], limitations: list[str]) -> list[Component]:
        components: list[Component] = []
        seen: set[str] = set()
        for row in sorted(rows, key=lambda r: int(r["item"]) if _ITEM.match(r["item"]) else 0):
            item = row["item"]
            if not _ITEM.match(item):
                limitations.append(f"position {item!r} is not a number - row skipped")
                continue
            if item in seen:
                limitations.append(f"position {item} listed more than once - first kept")
                continue
            seen.add(item)
            quantity = 1
            raw_qty = row.get("quantity", "")
            if raw_qty:
                m = _QTY.match(raw_qty.strip())
                if m and 1 <= int(m.group(1)) <= MAX_QUANTITY:
                    quantity = int(m.group(1))
                else:
                    limitations.append(
                        f"position {item}: quantity {raw_qty!r} not understood or above"
                        f" {MAX_QUANTITY} - counted as 1"
                    )
            fields = {
                key: row[column]
                for key, column in (
                    ("MPN", "mpn"),
                    ("Manufacturer", "manufacturer"),
                    ("Material", "material"),
                    ("Description", "description"),
                )
                if row.get(column)
            }
            fields["Item"] = item
            designators = (
                [f"MP{item}"]
                if quantity == 1
                else [f"MP{item}{_suffix(i)}" for i in range(quantity)]
            )
            for refdes in designators:
                components.append(
                    Component(refdes=refdes, value=row.get("description", ""), fields=dict(fields))
                )
            if len(components) > MAX_COMPONENTS:
                raise ParseError("too many components", code="file.too_large")
        return components
