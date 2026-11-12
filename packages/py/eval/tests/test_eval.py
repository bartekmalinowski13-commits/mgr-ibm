from __future__ import annotations

import math

import pytest

from bomagent_bom.grouping import group_components
from bomagent_bom.model import BomItem, BomVersion, Usage
from bomagent_cad import FileRef, parse_files
from bomagent_eval import (
    aggregate,
    comparison_markdown,
    detection_rate,
    detection_report,
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
    assert report.hallucinations.out_of_reference == 0
    assert report.hallucinations.coverage == 1.0
    assert report.diffs == []


@pytest.mark.parametrize("project", KICAD_PROJECTS)
def test_deterministic_baseline_on_fixtures(project):
    """Parser + grouping recovers all lines; MPNs missing from the schematic stay missing."""
    report = evaluate(
        baseline(project), reference(project), design=project, variant="B0", known_mpns=set()
    )
    assert report.designators.f1 == 1.0
    assert report.fields["value"].accuracy == 1.0
    assert report.fields["footprint"].accuracy == 1.0
    assert report.fields["dnp"].accuracy == 1.0
    assert report.hallucinations.unverified == 0
    # the reference puts identical parts on one line, so a schematic where only some
    # instances carry an MPN is split by deterministic grouping: lines are not perfect
    if project != "pulse-ox":
        assert report.lines.f1 < 1.0
    assert report.hallucinations.coverage < 1.0  # agents must complete the missing MPNs
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
    assert report.hallucinations.unverified == 1
    assert report.hallucinations.examples == ["TOTALLYFAKE-1"]
    assert report.hallucinations.rate == pytest.approx(0.5)
    # U1 is missing: unconditional accuracy counts it as wrong
    assert report.fields["value"].accuracy == 1.0
    assert report.fields["value"].accuracy_ref == pytest.approx(4 / 5)


def test_partial_prediction_cannot_score_full_accuracy():
    ref = reference("ecg-frontend")
    only_u1 = [i for i in ref if i.refdes == ["U1"]]
    report = evaluate(only_u1, ref)
    assert report.fields["mpn"].accuracy == 1.0
    assert report.fields["mpn"].accuracy_ref < 0.1


def test_duplicate_designators_and_real_mpns_outside_reference():
    ref = load_reference_csv("Reference,Value,MPN\nR1 R2,10k,RC0603FR-0710KL\n")
    pred = [
        BomItem(line=1, refdes=["R1", "R2"], quantity=2, value="10k", mpn="CRCW060310K0FKEA"),
        BomItem(line=2, refdes=["R2"], quantity=1, value="10k"),
    ]
    no_catalogue = evaluate(pred, ref)
    assert no_catalogue.designators.fp == 1  # R2 listed twice
    assert no_catalogue.hallucinations.out_of_reference == 1
    assert math.isnan(no_catalogue.hallucinations.rate)  # no catalogue: not measured
    with_catalogue = evaluate(pred, ref, known_mpns={"CRCW060310K0FKEA"})
    assert with_catalogue.hallucinations.rate == 0.0  # real part, just not the reference one
    abstain = evaluate(
        [BomItem(line=1, refdes=["R1", "R2"], quantity=2, value="10k")], ref, known_mpns=set()
    )
    assert abstain.hallucinations.coverage == 0.0
    assert math.isnan(abstain.hallucinations.rate)


def test_empty_prediction():
    report = evaluate([], reference("pulse-ox"))
    assert report.lines.f1 == 0.0
    assert math.isnan(report.lines.precision)
    assert math.isnan(report.fields["value"].accuracy)
    assert report.fields["value"].accuracy_ref == 0.0


def test_reference_without_designator_column():
    with pytest.raises(ValueError, match="designator"):
        load_reference_csv("Value,MPN\n10k,X\n")
    assert load_reference_csv("") == []


@pytest.mark.parametrize("seed", range(5))
def test_rule_pack_detects_all_injected_errors(seed):
    """Variant B's validator catches every injected error kind (fixture ecg-frontend)."""
    items = reference("ecg-frontend")
    baseline_findings = validate(items).findings
    mutated, errors = inject_errors(items, n=8, seed=seed)
    assert errors
    report = detection_report(errors, validate(mutated).findings, baseline_findings)
    assert report.detection_rate == 1.0
    assert report.false_alarm_rate <= 0.5


def test_detection_is_variant_neutral_and_needs_new_findings():
    from bomagent_bom.model import Finding, Severity

    items = reference("ecg-frontend")
    _, errors = inject_errors(items, n=1, seed=3, kinds=("drop_footprint",))
    (err,) = errors
    llm_finding = Finding(
        rule_id="agent.validator",
        severity=Severity.ERROR,
        message="footprint missing",
        refdes=[err.refdes],
        field="footprint",
    )
    assert detection_rate(errors, [llm_finding]) == 1.0
    assert detection_rate(errors, [llm_finding], baseline=[llm_finding]) == 0.0
    noise = Finding(rule_id="x", severity=Severity.WARNING, message="?", refdes=["ZZ1"])
    rep = detection_report(errors, [llm_finding, noise])
    assert (rep.false_alarms, rep.new_findings) == (1, 2)
    assert rep.by_kind == {"drop_footprint": (1, 1)}
    assert detection_report(errors, [noise]).by_kind == {"drop_footprint": (1, 0)}
    with pytest.raises(ValueError, match="at least one"):
        detection_rate([], [])


def test_injection_kinds_and_determinism():
    items = reference("eeg-2ch")
    a = inject_errors(items, n=6, seed=42)
    b = inject_errors(items, n=6, seed=42)
    assert a[1] == b[1]
    assert {e.kind for e in a[1]} <= set(DETECTED_BY)
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
    assert "MPN coverage" in md
    assert "fake-closed" in md
    table = comparison_markdown([report])
    assert "| ecg-frontend | B | fake-closed |" in table
    assert report.summary()["llm_calls"] == 3
