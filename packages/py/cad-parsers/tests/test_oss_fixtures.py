"""Real open-source projects (unmodified copies in evals/fixtures/kicad-oss)."""

from __future__ import annotations

import pytest

from bomagent_bom.grouping import group_components
from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_rules import validate
from bomagent_testing.data import FIXTURES

BIOAMP = FIXTURES / "kicad-oss" / "bioamp-exg-pill"


def _files(*names: str) -> list[FileRef]:
    return [FileRef.from_path(BIOAMP / n) for n in names]


def test_bioamp_exg_pill_kicad6():
    design = parse_files(
        _files(
            "BioAmp-EXG-Pill.kicad_sch", "BioAmp-EXG-Pill.kicad_pro", "BioAmp-EXG-Pill.kicad_pcb"
        )
    )
    assert design.source_format == "kicad6"
    assert design.confidence == 1.0
    refs = {c.refdes for c in design.components}
    assert len(refs) == 27
    assert {"U1", "J1", "J2", "R6", "C5"} <= refs
    by = {c.refdes: c for c in design.components}
    assert by["U1"].footprint == "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
    assert not any("footprints differ" in m for m in design.limitations)


def test_bioamp_rules_flag_assembly_time_placeholders():
    design = parse_files(_files("BioAmp-EXG-Pill.kicad_sch", "BioAmp-EXG-Pill.kicad_pro"))
    findings = validate(group_components(design)).findings
    flagged = {r for f in findings if f.rule_id == "value.parsable" for r in f.refdes}
    assert {"R6", "C5", "R12"} <= flagged  # RG, BPFC_C, BPFC_R


def test_bioamp_kicad5_legacy_is_explained():
    with pytest.raises(ParseError) as exc:
        parse_files(_files("BioAmp-EXG-Pill.sch"))
    assert exc.value.code == "kicad.legacy"
