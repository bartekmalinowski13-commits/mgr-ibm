from __future__ import annotations

import pytest

from bomagent_bom.grouping import group_components
from bomagent_bom.model import BomItem, BomVersion, Usage
from bomagent_cad import FileRef, parse_files
from bomagent_eval import (
    aggregate,
    comparison_markdown,
    detection_rate,
    evaluate,
    inject_errors,
    load_reference,
    load_reference_csv,
    pairwise_agreement,
    report_markdown,
)
from bomagent_eval.injection import DETECTED_BY
from bomagent_rules import validate
from bomagent_testing.data import KICAD_FIXTURES, KICAD_PROJECTS, kicad_project_paths


def baseline(project: str) -> list[BomItem]:
    design = parse_files([FileRef.from_path(p) for p in kicad_project_paths(project)])
    return group_components(design)


def reference(project: str) -> list[BomItem]:
    return load_reference(KICAD_FIXTURES / project / "reference_bom.csv")


@pytest.mark.parametrize("project", KICAD_PROJECTS)
def test_reference_against_itself_is_perfect(project):
    ref = reference(project)
    report = evaluate(ref, ref, design=project)
    assert report.lines.f1 == 1.0
    assert report.designators.f1 == 1.0
    assert all(s.accuracy == 1.0 for s in report.fields.values() if s.compared)
    assert report.hallucinations.rate == 0.0
    assert report.diffs == []


@pytest.mark.parametrize("project", KICAD_PROJECTS)
def test_deterministic_baseline_on_fixtures(project):
    """Parser + grouping recovers all lines; MPNs missing from the schematic stay missing."""
    report = evaluate(baseline(project), reference(project), design=project, variant="B0")
    assert report.designators.f1 == 1.0
    assert report.lines.recall == 1.0
    # eeg-2ch: C1 has no MPN in the schematic, so it cannot be merged with C102/C202 yet
    assert report.lines.f1 >= 0.9
    assert report.fields["value"].accuracy == 1.0
    assert report.fields["footprint"].accuracy == 1.0
    assert report.fields["dnp"].accuracy == 1.0
    assert report.hallucinations.hallucinated == 0
    if project != "pulse-ox":
        assert report.fields["mpn"].accuracy < 1.0  # agents must complete these
        assert any(d.field == "mpn" and d.predicted == "" for d in report.diffs)


def test_alternates_and_manufacturer_aliases_are_accepted():
    ref = load_reference_csv(
        "Reference,Value,Footprint,Manufacturer,MPN,MPN Alternates\n"
        "R1 R2,100k,R_0603,Yageo,RC0603FR-07100KL,ERJ-3EKF1003V\n"
        "C1,10u,C_0603,Samsung Electro-Mechanics,CL10A106KP8NNNC,\n"
    )
    pred = [
        BomItem(
            line=1,
            refdes=["R1", "R2"],
            quantity=2,
            value="100 kΩ",
            footprint="lib:R_0603",
            mpn="erj-3ekf1003v",
            manufacturer="Panasonic",
        ),
        BomItem(
            line=2,
            refdes=["C1"],
            quantity=1,
            value="10µF",
            footprint="C_0603",
            mpn="CL10A106KP8NNNC",
            manufacturer="Samsung",
        ),
    ]
    report = evaluate(pred, ref)
    assert report.fields["mpn"].accuracy == 1.0
    assert report.fields["value"].accuracy == 1.0
    assert report.fields["footprint"].accuracy == 1.0
    # Panasonic is wrong for the Yageo line (R1, R2); Samsung == Samsung Electro-Mechanics
    assert report.fields["manufacturer"].correct == 1
    assert report.fields["manufacturer"].compared == 3


def test_split_lines_extra_parts_and_hallucinations():
    ref = load_reference_csv("Reference,Value,MPN\nR1 R2 R3 R4,10k,RC0603FR-0710KL\nU1,X,ABC1\n")
    pred = [
        BomItem(line=1, refdes=["R1", "R2", "R3"], quantity=3, value="10k", mpn="RC0603FR-0710KL"),
        BomItem(line=2, refdes=["R4"], quantity=1, value="10k", mpn="TOTALLYFAKE-1"),
        BomItem(line=3, refdes=["R99"], quantity=1, value="1k"),
    ]
    report = evaluate(pred, ref, known_mpns={"KNOWN-1"})
    assert (report.lines.tp, report.lines.fp, report.lines.fn) == (1, 2, 1)
    assert (report.designators.tp, report.designators.fp, report.designators.fn) == (4, 1, 1)
    assert report.hallucinations.hallucinated == 1
    assert report.hallucinations.examples == ["TOTALLYFAKE-1"]
    assert report.hallucinations.rate == pytest.approx(0.5)


def test_empty_prediction():
    report = evaluate([], reference("pulse-ox"))
    assert report.lines.f1 == 0.0
    assert report.lines.precision == 0.0
    assert report.hallucinations.rate == 0.0


def test_reference_without_designator_column():
    with pytest.raises(ValueError, match="designator"):
        load_reference_csv("Value,MPN\n10k,X\n")
    assert load_reference_csv("") == []


@pytest.mark.parametrize("seed", range(5))
def test_rule_pack_detects_all_injected_errors(seed):
    """Variant B's validator catches every injected error kind (fixture ecg-frontend)."""
    items = reference("ecg-frontend")
    mutated, errors = inject_errors(items, n=8, seed=seed)
    assert errors
    findings = validate(mutated).findings
    assert detection_rate(errors, findings) == 1.0


def test_injection_kinds_and_determinism():
    items = reference("eeg-2ch")
    a = inject_errors(items, n=6, seed=42)
    b = inject_errors(items, n=6, seed=42)
    assert a[1] == b[1]
    assert {e.kind for e in a[1]} <= set(DETECTED_BY)
    assert detection_rate([], []) == 1.0
    assert detection_rate(a[1], []) == 0.0


def test_aggregate_and_agreement():
    ref = reference("pulse-ox")
    r1 = evaluate(ref, ref, variant="A")
    r2 = evaluate(baseline("pulse-ox"), ref, variant="A")
    agg = aggregate([r1, r2])
    assert agg.n == 2
    assert agg.mean["line_f1"] == 1.0
    assert agg.stdev["line_f1"] == 0.0
    assert aggregate([]).n == 0
    b1 = BomVersion(design_name="x", items=ref)
    b2 = BomVersion(design_name="x", items=baseline("pulse-ox"))
    assert pairwise_agreement([b1, b1]) == 1.0
    assert 0.0 < pairwise_agreement([b1, b2]) < 1.0
    assert pairwise_agreement([b1]) == 1.0


def test_markdown_reports():
    ref = reference("ecg-frontend")
    pred = BomVersion(
        design_name="ecg",
        items=baseline("ecg-frontend"),
        usage=Usage(llm_calls=3, input_tokens=100, output_tokens=50),
    )
    report = evaluate(pred, ref, design="ecg-frontend", variant="B", model="fake-closed")
    md = report_markdown(report)
    assert "Line precision" in md
    assert "| R1 | mpn |" in md
    assert "fake-closed" in md
    table = comparison_markdown([report])
    assert "| ecg-frontend | B | fake-closed | 100.0% |" in table
    assert report.summary()["llm_calls"] == 3
