"""DXF parts lists (M7): block attributes and exploded text tables, robustness."""

from __future__ import annotations

import pytest

from bomagent_bom.model import ParsedDesign
from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_testing.data import FIXTURES

# the parts list drawn in both fixtures (tools/make_format_fixtures.py: MECHANICAL)
EXPECTED = {
    "MP1": ("Enclosure, top and bottom shell", "1551KTBU", "Hammond", "ABS UL94-HB"),
    "MP3": ("Light pipe 3 mm", "LP-3MM-12", "Bivar", "PC"),
    "MP4": ("Gasket, front panel", "GSK-ECG-01", "", "Silicone 40 ShA"),
    "MP5": ("Product label (applied part BF symbol)", "LBL-ECG-01", "", "Polyester"),
}
SCREWS = {"MP2A", "MP2B", "MP2C", "MP2D"}


def check(design: ParsedDesign) -> None:
    assert design.source_format == "dxf"
    by_ref = {c.refdes: c for c in design.components}
    assert set(by_ref) == set(EXPECTED) | SCREWS
    for ref, (description, mpn, manufacturer, material) in EXPECTED.items():
        c = by_ref[ref]
        assert (c.value, c.field("MPN"), c.field("Manufacturer"), c.field("Material")) == (
            description,
            mpn,
            manufacturer,
            material,
        )
        assert c.kind == "mechanical"
    # quantity 4 -> four designators, so grouping yields one line with quantity 4
    assert {by_ref[r].field("MPN") for r in SCREWS} == {"ISO7380-M2x6-A2"}
    assert any("footprint" in lim for lim in design.limitations)


def test_parts_list_from_block_attributes():
    design = parse_files([FileRef.from_path(FIXTURES / "dxf" / "enclosure-attribs.dxf")])
    check(design)
    assert design.confidence >= 0.8


def test_parts_list_from_an_exploded_text_table():
    design = parse_files([FileRef.from_path(FIXTURES / "dxf" / "enclosure-table.dxf")])
    check(design)
    assert 0.5 <= design.confidence < 0.9  # layout heuristics: lower confidence
    assert any("text" in lim for lim in design.limitations)


def test_drawing_without_a_parts_list():
    import ezdxf

    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (10, 10))
    doc.modelspace().add_text("just a note", dxfattribs={"insert": (0, 0)})
    import io

    stream = io.StringIO()
    doc.write(stream)
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("drawing.dxf", stream.getvalue().encode())])
    assert err.value.code == "dxf.no_parts_list"


def test_broken_dxf():
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("broken.dxf", b"  0\nSECTION\n  2\nENTITIES\n  0\nTEXT\n 10\nabc\n")])
    assert err.value.code in {"dxf.malformed", "dxf.no_parts_list"}


def test_absurd_quantities_are_reported_not_expanded():
    import io

    import ezdxf

    doc = ezdxf.new()
    block = doc.blocks.new("ROW")
    for i, tag in enumerate(("POS", "PART_NO", "DESCRIPTION", "QTY")):
        block.add_attdef(tag, (i * 30, 0))
    insert = doc.modelspace().add_blockref("ROW", (0, 0))
    insert.add_auto_attribs({"POS": "1", "PART_NO": "W-1", "DESCRIPTION": "Washer", "QTY": "1e9"})
    stream = io.StringIO()
    doc.write(stream)
    design = parse_files([FileRef("big.dxf", stream.getvalue().encode())])
    assert [c.refdes for c in design.components] == ["MP1"]
    assert any("quantity" in lim for lim in design.limitations)
