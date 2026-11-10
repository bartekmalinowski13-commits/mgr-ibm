"""IPC-2581 and EDIF (M7): cross-format consistency with KiCad, robustness, detection."""

from __future__ import annotations

import pytest

from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad import FileRef, ParseError, UnsupportedFormatError, detect, parse_files
from bomagent_testing.data import FIXTURES, KICAD_PROJECTS, kicad_project_paths


def kicad(name: str) -> ParsedDesign:
    return parse_files([FileRef.from_path(p) for p in kicad_project_paths(name)])


def key(c: Component, *, full_footprint: bool) -> tuple[str, str, str, str, str, bool]:
    footprint = c.footprint if full_footprint else c.footprint.split(":")[-1]
    return (c.refdes, c.value, footprint, c.field("MPN"), c.field("Manufacturer"), c.dnp)


def same_parts(other: ParsedDesign, reference: ParsedDesign, *, full_footprint: bool) -> None:
    got = sorted(key(c, full_footprint=full_footprint) for c in other.bom_components())
    want = sorted(key(c, full_footprint=full_footprint) for c in reference.bom_components())
    assert got == want


# ------------------------------------------------------------------ IPC-2581


@pytest.mark.parametrize("name", KICAD_PROJECTS)
def test_ipc2581_export_matches_the_kicad_design(name):
    design = parse_files([FileRef.from_path(FIXTURES / "ipc2581" / f"{name}.xml")])
    assert design.source_format == "ipc2581"
    assert design.design_name == name
    assert design.confidence >= 0.9
    same_parts(design, kicad(name), full_footprint=False)


def test_ipc2581_without_bom_section_falls_back_to_placements():
    xml = (
        '<IPC-2581 revision="B" xmlns="http://webstds.ipc.org/2581"><Ecad><CadData>'
        '<Step name="board"><Component refDes="R1" packageRef="R0603" part="10k"/>'
        '<Component refDes="U1" packageRef="SOT23-5" part="OPA333"/></Step>'
        "</CadData></Ecad></IPC-2581>"
    )
    design = parse_files([FileRef("board.xml", xml.encode())])
    assert {(c.refdes, c.footprint) for c in design.components} == {
        ("R1", "R0603"),
        ("U1", "SOT23-5"),
    }
    assert design.confidence < 0.9
    assert any("no BOM section" in lim for lim in design.limitations)


@pytest.mark.parametrize(
    "payload",
    [
        # external entity (XXE)
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        '<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Bom name="&e;"/></IPC-2581>',
        # entity expansion (billion laughs)
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Bom name="&b;"/></IPC-2581>',
    ],
)
def test_ipc2581_rejects_dtds_and_entities(payload):
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("evil.xml", payload.encode())])
    assert err.value.code == "xml.forbidden"


def test_ipc2581_malformed_and_empty():
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("broken.xml", b"<IPC-2581 xmlns='http://webstds.ipc.org/2581'><Bom>")])
    assert err.value.code == "xml.malformed"
    empty = b'<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Content/></IPC-2581>'
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("empty.xml", empty)])
    assert err.value.code == "ipc2581.no_components"


def test_other_xml_is_not_mistaken_for_ipc2581():
    with pytest.raises(UnsupportedFormatError):
        detect([FileRef("pom.xml", b"<project><modelVersion>4.0.0</modelVersion></project>")])


# ------------------------------------------------------------------ EDIF


@pytest.mark.parametrize("name", KICAD_PROJECTS)
def test_edif_netlist_matches_the_kicad_design(name):
    design = parse_files([FileRef.from_path(FIXTURES / "edif" / f"{name}.edf")])
    assert design.source_format == "edif"
    assert design.confidence >= 0.9
    same_parts(design, kicad(name), full_footprint=True)
    assert design.nets is not None
    (gnd,) = [refs for net, refs in design.nets.items() if net == "GND"]
    assert len(gnd) == 2


def test_edif_instance_without_rename_and_unknown_properties():
    text = (
        "(edif board (edifVersion 2 0 0) (library design (cell board (view netlist (contents"
        " (instance R1 (viewRef netlist (cellRef RES (libraryRef lib)))"
        ' (property Value (string "4k7"))'
        ' (property Tolerance (string "1%")))'
        " (instance U1 (viewRef netlist (cellRef OPA (libraryRef lib))))"
        ")))))"
    )
    design = parse_files([FileRef("board.edif", text.encode())])
    by_ref = {c.refdes: c for c in design.components}
    assert by_ref["R1"].value == "4k7"
    assert by_ref["R1"].fields["Tolerance"] == "1%"
    assert by_ref["U1"].lib_id == "OPA"
    assert any("footprint" in lim for lim in design.limitations)  # none given


def test_edif_malformed():
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("broken.edf", b"(edif board (library")])
    assert err.value.code == "edif.malformed"
    with pytest.raises(ParseError) as err:
        parse_files([FileRef("empty.edf", b"(edif board (edifVersion 2 0 0))")])
    assert err.value.code == "edif.no_components"


def test_detection_by_content():
    assert detect([FileRef.from_path(FIXTURES / "ipc2581" / "pulse-ox.xml")]).format_id == (
        "ipc2581"
    )
    assert detect([FileRef.from_path(FIXTURES / "edif" / "pulse-ox.edf")]).format_id == "edif"
