"""CSV BOM import (reference BOMs for evaluation, existing customer BOMs).

Header detection is heuristic but conservative: a column is mapped only by a known alias;
unknown columns are kept as component fields. Designator cells may contain lists
(``R1, R2 R3``) and ranges (``R1-R4``), which are expanded. A ``Qty`` column that
disagrees with the number of designators is reported as a limitation, not silently fixed.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Literal

from bomagent_bom.dnp import parse_dnp
from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError

MAX_ROWS = 50_000
MAX_COMPONENTS = 100_000
ALIASES: dict[str, tuple[str, ...]] = {
    "refdes": (
        "reference",
        "references",
        "designator",
        "designators",
        "refdes",
        "ref des",
        "ref",
        "ref.",
        "part reference",
        "reference designator",
    ),
    "value": ("value", "val", "comment"),
    "footprint": ("footprint", "package", "pcb footprint", "case", "case/package"),
    # ordered by specificity: earlier aliases win when several columns match
    "mpn": (
        "manufacturer part number",
        "manufacturer_part_number",
        "mpn",
        "mfr pn",
        "mfr. part #",
        "mfr part number",
        "mpn#",
        "part number",
    ),
    "manufacturer": ("manufacturer", "mfr", "mfr.", "manufacturer name"),
    "quantity": ("qty", "quantity", "qty.", "count"),
    "dnp": ("dnp", "do not populate", "dnf", "populate"),
    "description": ("description", "desc"),
}
_RANGE = re.compile(r"^(?P<prefix>[A-Za-z_]+)(?P<a>\d+)\s*[-\u2013]\s*(?:[A-Za-z_]+)?(?P<b>\d+)$")
_SEP = re.compile(r"[\s,;]+")


def expand_refdes(cell: str) -> list[str]:
    out: list[str] = []
    for token in _SEP.split(cell.strip()):
        if not token:
            continue
        m = _RANGE.match(token)
        if m and int(m["b"]) >= int(m["a"]) and int(m["b"]) - int(m["a"]) < 1000:
            out.extend(f"{m['prefix']}{n}" for n in range(int(m["a"]), int(m["b"]) + 1))
        else:
            out.append(token)
    return out


def _map_headers(headers: list[str]) -> dict[str, int]:
    """Column per key; when several columns match, the most specific alias wins
    (e.g. "Manufacturer Part Number" over an internal "Part Number")."""
    best: dict[str, tuple[int, int]] = {}
    for idx, header in enumerate(headers):
        h = header.strip().strip("\ufeff").casefold()
        for key, aliases in ALIASES.items():
            if h in aliases:
                rank = aliases.index(h)
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, idx)
    return {key: idx for key, (_, idx) in best.items()}


class CsvBomParser:
    format_id = "csv-bom"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix not in {".csv", ".tsv", ".txt"}:
            return 0.0
        try:
            head = file.text().splitlines()[0] if file.data else ""
        except ParseError:
            return 0.0
        cells = re.split(r"[,;\t]", head)
        return 0.9 if "refdes" in _map_headers(cells) else 0.2

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        csvs = [f for f in files if f.suffix in {".csv", ".tsv", ".txt"}]
        if len(csvs) != 1:
            raise ParseError("expected exactly one CSV BOM file", code="csv.count")
        file = csvs[0]
        text = file.text()
        rows, header_idx = self._read_rows(text)
        if len(rows) > MAX_ROWS:
            raise ParseError(f"{file.name}: more than {MAX_ROWS} rows", code="file.too_large")
        if header_idx is None:
            raise ParseError(
                f"{file.name}: no designator column (expected e.g. 'Reference' or 'Designator')",
                code="csv.no_refdes",
            )
        headers = rows[header_idx]
        cols = _map_headers(headers)
        extra_cols = {
            i: h.strip() for i, h in enumerate(headers) if i not in cols.values() and h.strip()
        }
        limitations: list[str] = []
        components: list[Component] = []
        seen: set[str] = set()
        for n, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
            if any(c.strip() for c in row):
                self._row(n, row, headers, cols, extra_cols, seen, components, limitations)
        confidence = 1.0 if not limitations else max(0.5, 1.0 - 0.02 * len(limitations))
        return ParsedDesign(
            design_name=file.name.rsplit(".", 1)[0],
            source_format=self.format_id,
            components=components,
            confidence=confidence,
            limitations=limitations,
            files=[file.source()],
            parser_version=self.version,
        )

    @staticmethod
    def _read_rows(text: str) -> tuple[list[list[str]], int | None]:
        """Pick the delimiter whose parse yields a recognisable header row (preambles and
        European ``;`` files are common; ``csv.Sniffer`` alone guesses wrong on them)."""
        best: tuple[int, list[list[str]], int | None] = (-1, [], None)
        for delimiter in (",", ";", "\t"):
            try:
                rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            except csv.Error as exc:
                raise ParseError(f"malformed CSV: {exc}", code="csv.malformed") from exc
            for i, row in enumerate(rows[:20]):
                mapped = _map_headers(row)
                if "refdes" in mapped and len(mapped) > best[0]:
                    best = (len(mapped), rows, i)
                    break
        if best[2] is None:
            return [], None
        return best[1], best[2]

    @staticmethod
    def _row(
        n: int,
        row: list[str],
        headers: list[str],
        cols: dict[str, int],
        extra_cols: dict[int, str],
        seen: set[str],
        components: list[Component],
        limitations: list[str],
    ) -> None:
        def cell(key: str) -> str:
            i = cols.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        refs = expand_refdes(cell("refdes"))
        if not refs:
            limitations.append(f"row {n}: no designators, skipped")
            return
        qty = cell("quantity")
        if qty.isdigit() and int(qty) != len(refs):
            limitations.append(f"row {n}: Qty {qty} but {len(refs)} designators")
        dnp = False
        if "dnp" in cols:
            column: Literal["dnp", "populate"] = (
                "populate" if headers[cols["dnp"]].strip().casefold() == "populate" else "dnp"
            )
            parsed = parse_dnp(cell("dnp"), column)
            if parsed is None:
                limitations.append(f"row {n}: unrecognised DNP value {cell('dnp')!r}")
            dnp = bool(parsed)
        fields = {
            name: row[i].strip()
            for i, name in extra_cols.items()
            if i < len(row) and row[i].strip()
        }
        for key, label in (
            ("mpn", "MPN"),
            ("manufacturer", "Manufacturer"),
            ("description", "Description"),
        ):
            if cell(key):
                fields[label] = cell(key)
        if len(components) + len(refs) > MAX_COMPONENTS:
            raise ParseError(f"more than {MAX_COMPONENTS} components", code="file.too_large")
        for ref in refs:
            if ref in seen:
                limitations.append(f"row {n}: duplicate designator {ref}")
                continue
            seen.add(ref)
            try:
                components.append(
                    Component(
                        refdes=ref,
                        value=cell("value"),
                        footprint=cell("footprint"),
                        fields=fields,
                        dnp=dnp,
                    )
                )
            except ValueError:
                limitations.append(f"row {n}: invalid designator {ref!r}")
