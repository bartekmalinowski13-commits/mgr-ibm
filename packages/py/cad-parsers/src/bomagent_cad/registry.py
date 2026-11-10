"""Parser registry: format detection and honest "not supported (yet)" guidance."""

from __future__ import annotations

from bomagent_bom.model import ParsedDesign
from bomagent_cad.base import FileRef, FormatParser, UnsupportedFormatError
from bomagent_cad.csv_bom import CsvBomParser
from bomagent_cad.dxf import DxfParser
from bomagent_cad.edif import EdifParser
from bomagent_cad.ipc2581 import Ipc2581Parser
from bomagent_cad.kicad import KicadParser
from bomagent_cad.odbpp import OdbppParser

# extension -> (hint code for the UI i18n catalogue, English hint)
UNSUPPORTED_HINTS: dict[str, tuple[str, str]] = {
    ".brd": (
        "unsupported.allegro_brd",
        "Allegro .brd is not parsed directly. Export IPC-2581 from Allegro and upload it.",
    ),
    ".schdoc": (
        "unsupported.altium",
        "Altium files are not supported yet. Export a BOM (CSV), IPC-2581 or ODB++.",
    ),
    ".pcbdoc": (
        "unsupported.altium",
        "Altium files are not supported yet. Export a BOM (CSV), IPC-2581 or ODB++.",
    ),
    ".prjpcb": (
        "unsupported.altium",
        "Altium files are not supported yet. Export a BOM (CSV), IPC-2581 or ODB++.",
    ),
    ".dsn": (
        "unsupported.orcad",
        "OrCAD Capture files are not supported yet. Export an EDIF netlist or a CIS BOM.",
    ),
    ".dwg": (
        "unsupported.dwg",
        "DWG is not supported yet. Save the drawing as DXF and upload it.",
    ),
    ".xlsx": ("unsupported.xlsx", "Save the spreadsheet as CSV and upload it."),
}


def default_parsers() -> list[FormatParser]:
    return [
        KicadParser(),
        Ipc2581Parser(),
        EdifParser(),
        OdbppParser(),
        DxfParser(),
        CsvBomParser(),
    ]


def detect(files: list[FileRef], parsers: list[FormatParser] | None = None) -> FormatParser:
    parsers = parsers or default_parsers()
    best: tuple[float, FormatParser | None] = (0.0, None)
    for parser in parsers:
        score = max((parser.sniff(f) for f in files), default=0.0)
        if score > best[0]:
            best = (score, parser)
    if best[1] is None or best[0] < 0.5:
        for f in files:
            hint = UNSUPPORTED_HINTS.get(f.suffix)
            if hint:
                raise UnsupportedFormatError(hint[1], code=hint[0])
        raise UnsupportedFormatError(
            "No supported design file found"
            " (KiCad 6-9 .kicad_sch, IPC-2581, EDIF, ODB++, DXF, CSV BOM).",
            code="unsupported.unknown",
        )
    return best[1]


def parse_files(files: list[FileRef], parsers: list[FormatParser] | None = None) -> ParsedDesign:
    return detect(files, parsers).parse(files)
