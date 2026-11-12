"""BOM export (CSV for procurement tools, JSON for machines)."""

from __future__ import annotations

import csv
import io

from bomagent_bom.model import BomVersion
from bomagent_bom.refdes import compress

CSV_COLUMNS = (
    "Line",
    "Qty",
    "RefDes",
    "Value",
    "Footprint",
    "Package",
    "Manufacturer",
    "MPN",
    "Description",
    "DNP",
    "Decided by",
)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Neutralise spreadsheet formula injection (OWASP CSV injection)."""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def to_csv(bom: BomVersion, *, compact_refdes: bool = False) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for item in bom.items:
        decided = sorted({p.kind.value for p in item.provenance.values()})
        writer.writerow(
            [
                _cell(x)
                for x in (
                    item.line,
                    item.quantity,
                    compress(item.refdes) if compact_refdes else " ".join(item.refdes),
                    item.value,
                    item.footprint,
                    item.package or "",
                    item.manufacturer,
                    item.mpn,
                    item.description,
                    "DNP" if item.dnp else "",
                    "+".join(decided),
                )
            ]
        )
    return buf.getvalue()


def to_json(bom: BomVersion) -> str:
    return bom.model_dump_json(indent=2)
