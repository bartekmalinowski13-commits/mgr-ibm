"""PDF BOM tables (M7): consistency with the CSV reference BOM, scans, robustness."""

from __future__ import annotations

import pytest

from bomagent_bom.model import ParsedDesign
from bomagent_cad import FileRef, ParseError, detect, parse_files
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES, KICAD_PROJECTS


def rows(design: ParsedDesign) -> list[tuple[str, str, str, str, str, bool]]:
    return sorted(
        (
            c.refdes,
            c.value,
            c.footprint.split(":")[-1],
            c.field("MPN"),
            c.field("Manufacturer"),
            c.dnp,
        )
        for c in design.components
    )


@pytest.mark.parametrize("name", KICAD_PROJECTS)
def test_pdf_bom_matches_the_csv_reference(name):
    pdf = parse_files([FileRef.from_path(FIXTURES / "pdf-bom" / f"{name}.pdf")])
    csv = parse_files([FileRef.from_path(KICAD_FIXTURES / name / "reference_bom.csv")])
    assert pdf.source_format == "pdf-bom"
    assert rows(pdf) == rows(csv)
    # read from page layout: lower confidence, flagged for review (FORMATS.md)
    assert 0.5 <= pdf.confidence < 0.9
    assert any("review" in lim for lim in pdf.limitations)


def test_pdf_without_text_is_reported_as_a_scan():
    blank = (FIXTURES / "pdf-bom" / "pulse-ox.pdf").read_bytes()
    # replace every text operator: the page keeps its structure but has no text layer
    start = blank.index(b"stream\n") + 7
    end = blank.index(b"\nendstream")
    no_text = blank[:start] + b" " * (end - start) + blank[end:]
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("scan.pdf", no_text)])
    assert err.value.code == "pdf.no_text"


def test_pdf_without_a_bom_table():
    text = (FIXTURES / "pdf-bom" / "pulse-ox.pdf").read_bytes().replace(b"(Designator)", b"(Notes)")
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("notes.pdf", text)])
    assert err.value.code == "pdf.no_bom_table"


def test_broken_pdf():
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("broken.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog")])
    assert err.value.code == "pdf.malformed"


def test_detection():
    assert detect([FileRef.from_path(FIXTURES / "pdf-bom" / "eeg-2ch.pdf")]).format_id == "pdf-bom"
