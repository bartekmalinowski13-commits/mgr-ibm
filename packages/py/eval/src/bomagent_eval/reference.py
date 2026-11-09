"""Reference ("ground truth") BOMs for evaluation.

A reference BOM is a CSV with one row per BOM line; ``MPN Alternates`` lists other part
numbers an expert accepts for the same line (a generic 10 kΩ 0603 resistor has many
valid MPNs - scoring only one would punish correct answers).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from bomagent_bom.model import BomItem
from bomagent_bom.packages import package_from_footprint
from bomagent_bom.refdes import kind_of
from bomagent_bom.values import normalize_value
from bomagent_cad.csv_bom import ALIASES, expand_refdes

ALTERNATES_HEADERS = {"mpn alternates", "alternates", "alternative mpn", "alt mpn"}


def _col(headers: list[str], key: str) -> int | None:
    for i, h in enumerate(headers):
        if h.strip().casefold() in ALIASES[key]:
            return i
    return None


def load_reference_csv(text: str) -> list[BomItem]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    headers = rows[0]
    cols = {k: _col(headers, k) for k in ALIASES}
    alt_col = next(
        (i for i, h in enumerate(headers) if h.strip().casefold() in ALTERNATES_HEADERS), None
    )
    if cols["refdes"] is None:
        raise ValueError("reference BOM has no designator column")

    def get(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    items: list[BomItem] = []
    for row in rows[1:]:
        refs = expand_refdes(get(row, cols["refdes"]))
        if not refs:
            continue
        kind = kind_of(refs[0])
        value = get(row, cols["value"])
        footprint = get(row, cols["footprint"])
        fields = {}
        if alt := get(row, alt_col):
            fields["mpn_alternates"] = alt
        items.append(
            BomItem(
                line=len(items) + 1,
                refdes=refs,
                quantity=len(refs),
                kind=kind,
                value=value,
                value_normalized=normalize_value(value, kind),
                footprint=footprint,
                package=package_from_footprint(footprint),
                manufacturer=get(row, cols["manufacturer"]),
                mpn=get(row, cols["mpn"]),
                dnp=get(row, cols["dnp"]).casefold() in {"dnp", "yes", "true", "1", "x"},
                fields=fields,
            )
        )
    return items


def load_reference(path: str | Path) -> list[BomItem]:
    return load_reference_csv(Path(path).read_text(encoding="utf-8"))
