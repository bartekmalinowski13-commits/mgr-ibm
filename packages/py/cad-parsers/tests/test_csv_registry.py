from __future__ import annotations

import pytest

from bomagent_cad import FileRef, ParseError, UnsupportedFormatError, detect, parse_files
from bomagent_cad.csv_bom import CsvBomParser, expand_refdes
from bomagent_testing.data import KICAD_FIXTURES as FIXTURES
from bomagent_testing.data import kicad_project_paths


def project_files(name: str, *, with_pro: bool = True) -> list[FileRef]:
    return [FileRef.from_path(p) for p in kicad_project_paths(name, with_pro=with_pro)]


def test_expand_refdes():
    assert expand_refdes("R1-R3, C5 C6;U1") == ["R1", "R2", "R3", "C5", "C6", "U1"]
    assert expand_refdes("R5-3") == ["R5-3"]


def test_reference_bom_fixture_parses():
    f = FileRef.from_path(FIXTURES / "ecg-frontend" / "reference_bom.csv")
    design = parse_files([f])
    assert design.source_format == "csv-bom"
    by_ref = {c.refdes: c for c in design.components}
    assert by_ref["R9"].dnp is True
    assert by_ref["R5"].field("MPN") == "RC0603FR-07100KL"
    assert by_ref["R5"].field("MPN Alternates") == "ERJ-3EKF1003V CRCW0603100KFKEA"
    assert design.limitations == []


def test_semicolon_csv_with_preamble_qty_mismatch_and_duplicates():
    text = (
        "Project X BOM\n"
        "Designator;Comment;Package;Qty;Mfr;Mfr. Part #;Populate\n"
        "R1-R3;10k;0603;2;Yageo;RC0603FR-0710KL;yes\n"
        "R3;1k;0603;1;;;no\n"
        ";;;;;;\n"
        "??;x;;1;;;\n"
    )
    design = CsvBomParser().parse([FileRef("bom.csv", text.encode())])
    refs = [c.refdes for c in design.components]
    assert refs == ["R1", "R2", "R3"]
    assert any("Qty 2 but 3" in m for m in design.limitations)
    assert any("duplicate designator R3" in m for m in design.limitations)
    assert any("invalid designator" in m for m in design.limitations)
    assert design.components[0].field("Manufacturer") == "Yageo"
    assert design.confidence < 1.0


def test_dnp_column():
    text = "Reference,Value,DNP\nR1,10k,\nR2,10k,DNP\n"
    design = CsvBomParser().parse([FileRef("b.csv", text.encode())])
    assert [c.dnp for c in design.components] == [False, True]


def test_csv_without_designator_column():
    with pytest.raises(ParseError) as exc:
        CsvBomParser().parse([FileRef("b.csv", b"Value,Qty\n10k,1\n")])
    assert exc.value.code == "csv.no_refdes"


def test_csv_requires_exactly_one_file():
    with pytest.raises(ParseError):
        CsvBomParser().parse([])


def test_detect_prefers_kicad_for_projects():
    assert detect(project_files("ecg-frontend")).format_id == "kicad"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("board.brd", "unsupported.allegro_brd"),
        ("x.SchDoc", "unsupported.altium"),
        ("y.dwg", "unsupported.dwg"),
        ("z.bin", "unsupported.unknown"),
    ],
)
def test_unsupported_formats_explain_next_step(name, code):
    with pytest.raises(UnsupportedFormatError) as exc:
        parse_files([FileRef(name, b"\x00\x01")])
    assert exc.value.code == code


def test_sniff_csv():
    p = CsvBomParser()
    assert p.sniff(FileRef("a.csv", b"Reference,Value\n")) == 0.9
    assert p.sniff(FileRef("a.csv", b"foo,bar\n")) == 0.2
    assert p.sniff(FileRef("a.csv", b"\xff\xfe")) == 0.0
    assert p.sniff(FileRef("a.kicad_sch", b"")) == 0.0


def test_file_too_large(tmp_path, monkeypatch):
    import bomagent_cad.base as base

    monkeypatch.setattr(base, "MAX_FILE_BYTES", 3)
    p = tmp_path / "big.csv"
    p.write_bytes(b"12345")
    with pytest.raises(ParseError) as exc:
        FileRef.from_path(p)
    assert exc.value.code == "file.too_large"
