from __future__ import annotations

import json

import pytest

from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_cad.kicad import KicadParser, kicad_major
from bomagent_testing.data import KICAD_FIXTURES as FIXTURES
from bomagent_testing.data import KICAD_PROJECTS as PROJECTS
from bomagent_testing.data import kicad_project_paths


def project_files(name: str, *, with_pro: bool = True) -> list[FileRef]:
    return [FileRef.from_path(p) for p in kicad_project_paths(name, with_pro=with_pro)]


@pytest.mark.parametrize("project", PROJECTS)
def test_fixture_matches_expected_components(project):
    design = parse_files(project_files(project))
    expected = json.loads((FIXTURES / project / "expected_components.json").read_text())
    got = {c.refdes: c for c in design.bom_components()}
    assert set(got) == {e["refdes"] for e in expected}
    for e in expected:
        c = got[e["refdes"]]
        assert c.value == e["value"]
        assert c.footprint == e["footprint"]
        assert c.dnp == e["dnp"]
        assert c.field("MPN") == e["mpn_in_schematic"]
    assert design.confidence == 1.0
    assert all(len(f.sha256) == 64 for f in design.files)


def test_versions_are_detected():
    assert parse_files(project_files("pulse-ox")).source_format == "kicad6"
    assert parse_files(project_files("ecg-frontend")).source_format == "kicad8"
    assert parse_files(project_files("eeg-2ch")).source_format == "kicad9"
    assert kicad_major(20230121) == 7


def test_sheet_used_twice_gets_both_instances():
    design = parse_files(project_files("eeg-2ch"))
    refs = {c.refdes: c.sheet_path for c in design.components}
    assert refs["U101"] == "/Channel A"
    assert refs["U201"] == "/Channel B"
    assert design.sheets == ["/", "/Channel A", "/Channel B"]


def test_multi_unit_symbol_yields_one_component():
    design = parse_files(project_files("eeg-2ch"))
    assert [c.refdes for c in design.components].count("U102") == 1


def test_power_symbols_and_not_in_bom_parts():
    design = parse_files(project_files("ecg-frontend"))
    refs = [c.refdes for c in design.components]
    assert not any(r.startswith("#") for r in refs)
    holes = [c for c in design.components if c.refdes.startswith("H")]
    assert holes
    assert not any(h.in_bom for h in holes)
    assert all(not c.refdes.startswith("H") for c in design.bom_components())


def test_components_are_naturally_sorted():
    refs = [c.refdes for c in parse_files(project_files("ecg-frontend")).components]
    rs = [r for r in refs if r.startswith("R")]
    assert rs == sorted(rs, key=lambda r: int(r[1:]))


def test_root_found_without_project_file():
    design = parse_files(project_files("ecg-frontend", with_pro=False))
    assert design.design_name == "ecg-frontend"


def test_missing_sheet_lowers_confidence():
    files = [f for f in project_files("ecg-frontend") if f.name != "power.kicad_sch"]
    design = parse_files(files)
    assert design.confidence < 1.0
    assert any("power.kicad_sch" in m for m in design.limitations)
    assert "U3" not in {c.refdes for c in design.components}


def test_ambiguous_root_without_project_file():
    a = FileRef("a.kicad_sch", b'(kicad_sch (version 20231120) (uuid "a"))')
    b = FileRef("b.kicad_sch", b'(kicad_sch (version 20231120) (uuid "b"))')
    with pytest.raises(ParseError) as exc:
        parse_files([a, b])
    assert exc.value.code == "kicad.ambiguous_root"


SIMPLE = """(kicad_sch (version 20231120) (generator "eeschema") (uuid "root")
  (symbol (lib_id "Device:R") (in_bom yes) (on_board yes) (dnp no) (uuid "s1")
    (property "Reference" "R?" (at 0 0 0))
    (property "Value" "10k" (at 0 0 0)))
  (symbol (lib_id "Device:R") (in_bom yes) (on_board yes) (dnp no) (uuid "s2")
    (property "Reference" "R1" (at 0 0 0))
    (property "Value" "1k" (at 0 0 0))))
"""


def test_unannotated_symbols_are_reported_and_skipped():
    design = parse_files([FileRef("x.kicad_sch", SIMPLE.encode())])
    assert [c.refdes for c in design.components] == ["R1"]
    assert any("unannotated" in m for m in design.limitations)
    assert any("no instance data" in m for m in design.limitations)
    assert design.confidence < 1.0


def test_pcb_fills_missing_footprints_and_reports_mismatch():
    sch = SIMPLE.replace('"R?"', '"R2"').encode()
    pcb = b"""(kicad_pcb (version 20231014)
      (footprint "Resistor_SMD:R_0603_1608Metric" (property "Reference" "R1"))
      (footprint "Resistor_SMD:R_0402_1005Metric" (fp_text reference "R2" (at 0 0)))
      (footprint "Resistor_SMD:R_0402_1005Metric" (property "Reference" "R99")))"""
    design = parse_files([FileRef("x.kicad_sch", sch), FileRef("x.kicad_pcb", pcb)])
    by_ref = {c.refdes: c for c in design.components}
    assert by_ref["R1"].footprint == "Resistor_SMD:R_0603_1608Metric"
    assert not any("footprints differ" in m for m in design.limitations)


def test_pcb_footprint_mismatch():
    sch = (
        SIMPLE.replace('"R?"', '"R2"')
        .replace(
            '(property "Value" "1k" (at 0 0 0))',
            '(property "Value" "1k" (at 0 0 0)) (property "Footprint" "R_0805" (at 0 0 0))',
        )
        .encode()
    )
    pcb = b'(kicad_pcb (footprint "R_0402" (property "Reference" "R1")))'
    design = parse_files([FileRef("x.kicad_sch", sch), FileRef("x.kicad_pcb", pcb)])
    assert any("footprints differ for: R1" in m for m in design.limitations)


def test_unreadable_pcb_is_a_limitation_not_an_error():
    files = [FileRef("x.kicad_sch", SIMPLE.encode()), FileRef("x.kicad_pcb", b"(kicad_pcb (")]
    assert any("could not be read" in m for m in parse_files(files).limitations)
    files = [FileRef("x.kicad_sch", SIMPLE.encode()), FileRef("x.kicad_pcb", b"(other)")]
    assert any("not a KiCad PCB" in m for m in parse_files(files).limitations)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"(kicad_sch (version 20231120) (symbol", "kicad.malformed"),
        (b"(kicad_sch (version 2019))", "kicad.legacy"),
        (b"(kicad_sch (version abc))", "kicad.malformed"),
        (b"(other_file (version 20231120))", "kicad.not_schematic"),
        (b"\xff\xfe\x00garbage", "file.encoding"),
        (b"(kicad_sch " + b"(a " * 5000 + b")" * 5001, "kicad.malformed"),
    ],
)
def test_robustness_against_bad_files(data, code):
    with pytest.raises(ParseError) as exc:
        KicadParser().parse([FileRef("bad.kicad_sch", data)])
    assert exc.value.code == code


def test_legacy_kicad5_is_explained():
    legacy = FileRef("old.sch", b"EESchema Schematic File Version 4\n")
    with pytest.raises(ParseError) as exc:
        parse_files([legacy])
    assert exc.value.code == "kicad.legacy"


def test_no_schematic_in_upload():
    with pytest.raises(ParseError):
        KicadParser().parse([FileRef("x.kicad_pro", b"{}")])


def test_recursive_sheets_are_rejected():
    loop = b"""(kicad_sch (version 20231120) (uuid "r")
      (sheet (uuid "s") (property "Sheetname" "S" (at 0 0 0))
             (property "Sheetfile" "loop.kicad_sch" (at 0 0 0))))"""
    root = b"""(kicad_sch (version 20231120) (uuid "root")
      (sheet (uuid "s0") (property "Sheetname" "L" (at 0 0 0))
             (property "Sheetfile" "loop.kicad_sch" (at 0 0 0))))"""
    with pytest.raises(ParseError) as exc:
        parse_files(
            [
                FileRef("root.kicad_sch", root),
                FileRef("loop.kicad_sch", loop),
                FileRef("root.kicad_pro", b"{}"),
            ]
        )
    assert exc.value.code == "kicad.recursion"


def test_sniff_scores():
    p = KicadParser()
    assert p.sniff(FileRef("a.kicad_sch", b"(kicad_sch (version 1))")) == 1.0
    assert p.sniff(FileRef("a.kicad_sch", b"junk")) == 0.3
    assert p.sniff(FileRef("a.kicad_pcb", b"")) == 0.5
    assert p.sniff(FileRef("a.txt", b"")) == 0.0


def _sch(body: str, uuid: str = "root", version: int = 20231120) -> bytes:
    return f'(kicad_sch (version {version}) (generator "eeschema") (uuid "{uuid}") {body})'.encode()


def _sym(
    ref: str, value: str, lib: str = "Device:R", uid: str = "s", unit: int = 1, instances: str = ""
) -> str:
    return (
        f'(symbol (lib_id "{lib}") (unit {unit}) (in_bom yes) (on_board yes) (dnp no)'
        f' (uuid "{uid}") (property "Reference" "{ref}" (at 0 0 0))'
        f' (property "Value" "{value}" (at 0 0 0)) {instances})'
    )


def _sheet(file: str, uid: str, name: str = "S") -> str:
    return (
        f'(sheet (uuid "{uid}") (property "Sheetname" "{name}" (at 0 0 0))'
        f' (property "Sheetfile" "{file}" (at 0 0 0)))'
    )


def test_exponential_sheet_fanout_is_bounded():
    # each level instantiates the next twice: 2^20 walks without a budget
    files = [
        FileRef("top.kicad_pro", b"{}"),
        FileRef("top.kicad_sch", _sch(_sheet("l0.kicad_sch", "a") + _sheet("l0.kicad_sch", "b"))),
    ]
    for level in range(20):
        nxt = f"l{level + 1}.kicad_sch"
        files.append(
            FileRef(
                f"l{level}.kicad_sch",
                _sch(_sheet(nxt, f"a{level}") + _sheet(nxt, f"b{level}"), uuid=f"u{level}"),
            )
        )
    files.append(FileRef("l20.kicad_sch", _sch(_sym("R1", "1k"), uuid="leaf")))
    with pytest.raises(ParseError) as exc:
        parse_files(files)
    assert exc.value.code == "kicad.too_complex"


def test_sheet_including_itself_twice_is_rejected():
    files = [
        FileRef("top.kicad_pro", b"{}"),
        FileRef("top.kicad_sch", _sch(_sheet("loop.kicad_sch", "a"))),
        FileRef(
            "loop.kicad_sch",
            _sch(_sheet("loop.kicad_sch", "x") + _sheet("loop.kicad_sch", "y"), uuid="l"),
        ),
    ]
    with pytest.raises(ParseError) as exc:
        parse_files(files)
    assert exc.value.code == "kicad.recursion"


def test_duplicate_designator_on_different_symbols_is_kept_and_reported():
    sch = _sch(_sym("R1", "10k", uid="a") + _sym("R1", "100n", lib="Device:C", uid="b"))
    design = parse_files([FileRef("x.kicad_sch", sch)])
    assert [c.value for c in design.components] == ["10k", "100n"]
    assert any("duplicate designators" in m for m in design.limitations)
    assert design.confidence < 1.0


def test_other_project_instances_are_ignored():
    inst = (
        '(instances (project "x" (path "/root" (reference "R1") (unit 1)))'
        ' (project "old-copy" (path "/root" (reference "R7") (unit 1))))'
    )
    design = parse_files([FileRef("x.kicad_sch", _sch(_sym("R1", "1k", instances=inst)))])
    assert [c.refdes for c in design.components] == ["R1"]
    assert any("old-copy" in m for m in design.limitations)


def test_kicad6_per_instance_value_and_footprint():
    child = _sch(_sym("R1", "10k", uid="sym"), uuid="c", version=20211014)
    root = _sch(
        _sheet("ch.kicad_sch", "s1", "A")
        + _sheet("ch.kicad_sch", "s2", "B")
        + '(symbol_instances (path "/s1/sym" (reference "R101") (unit 1) (value "10k")'
        ' (footprint "R_0603")) (path "/s2/sym" (reference "R201") (unit 1) (value "22k")'
        ' (footprint "R_0805")))',
        version=20211014,
    )
    design = parse_files(
        [
            FileRef("top.kicad_sch", root),
            FileRef("ch.kicad_sch", child),
            FileRef("top.kicad_pro", b"{}"),
        ]
    )
    by = {c.refdes: c for c in design.components}
    assert (by["R101"].value, by["R101"].footprint) == ("10k", "R_0603")
    assert (by["R201"].value, by["R201"].footprint) == ("22k", "R_0805")


def test_sheetfile_in_subdirectory_and_invalid_designator():
    root = _sch(_sheet("sub/ch.kicad_sch", "s1"))
    child = _sch(_sym("R1.1", "1k", uid="q") + _sym("R2", "1k", uid="w"), uuid="c")
    design = parse_files(
        [
            FileRef("top.kicad_sch", root),
            FileRef("ch.kicad_sch", child),
            FileRef("top.kicad_pro", b"{}"),
        ]
    )
    assert [c.refdes for c in design.components] == ["R2"]
    assert any("invalid designator 'R1.1'" in m for m in design.limitations)


def test_reused_sheet_without_instance_data_lowers_confidence():
    root = _sch(_sheet("ch.kicad_sch", "s1") + _sheet("ch.kicad_sch", "s2"))
    child = _sch(_sym("R1", "1k", uid="q"), uuid="c")
    design = parse_files(
        [
            FileRef("top.kicad_sch", root),
            FileRef("ch.kicad_sch", child),
            FileRef("top.kicad_pro", b"{}"),
        ]
    )
    assert design.confidence <= 0.8
    assert any("no instance data" in m for m in design.limitations)
