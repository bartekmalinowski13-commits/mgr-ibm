"""BOM export (CSV for procurement tools, JSON for machines)."""

from __future__ import annotations

import csv
import io
import zipfile
from xml.sax.saxutils import escape

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
DEMO_COLUMN = "Demo"
DEMO_NOTICE = "illustrative: deterministic demo model"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Neutralise spreadsheet formula injection (OWASP CSV injection)."""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def to_csv(bom: BomVersion, *, compact_refdes: bool = False, demo: bool = False) -> str:
    """``demo`` appends a ``Demo`` column to every row: the BOM came from the fake model."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow((*CSV_COLUMNS, DEMO_COLUMN) if demo else CSV_COLUMNS)
    for item in bom.items:
        decided = sorted({p.kind.value for p in item.provenance.values()})
        row = [
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
        writer.writerow([*row, DEMO_NOTICE] if demo else row)
    return buf.getvalue()


_XML_ILLEGAL = dict.fromkeys(c for c in range(32) if c not in (9, 10, 13))


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xlsx_text(value: object) -> str:
    return escape(str(value).translate(_XML_ILLEGAL))


_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_SHEET_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml"


def to_xlsx(bom: BomVersion, *, compact_refdes: bool = False, demo: bool = False) -> bytes:
    """Same table as :func:`to_csv` as a minimal XLSX workbook (stdlib only).

    Text cells are written as inline strings and numbers as numbers - never as formulas -
    so cell content cannot be evaluated by the spreadsheet application.
    """
    header = (*CSV_COLUMNS, DEMO_COLUMN) if demo else CSV_COLUMNS
    rows: list[list[object]] = [list(header)]
    for item in bom.items:
        decided = sorted({p.kind.value for p in item.provenance.values()})
        row: list[object] = [
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
        ]
        rows.append([*row, DEMO_NOTICE] if demo else row)
    sheet_rows = []
    for r, values in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(values):
            ref = f"{_col(c)}{r}"
            if isinstance(value, int) and not isinstance(value, bool) and r > 1:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xlsx_text(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    parts = {
        "[Content_Types].xml": (
            f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{_SHEET_CT}.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml"'
            f' ContentType="{_SHEET_CT}.worksheet+xml"/></Types>'
        ),
        "_rels/.rels": (
            f'{_XML}<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            f'{_XML}<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets>'
            '<sheet name="BOM" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'{_XML}<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            f'{_XML}<worksheet xmlns="{_NS}"><sheetData>{"".join(sheet_rows)}</sheetData>'
            "</worksheet>"
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)
    return buf.getvalue()


def to_json(bom: BomVersion) -> str:
    return bom.model_dump_json(indent=2)
