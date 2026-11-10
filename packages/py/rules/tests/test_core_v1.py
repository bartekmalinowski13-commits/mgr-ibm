from __future__ import annotations

import pytest

from bomagent_bom.grouping import group_components
from bomagent_bom.model import (
    AppliedPart,
    BomItem,
    BomVersion,
    PowerSource,
    Requirements,
    Severity,
)
from bomagent_cad import FileRef, parse_files
from bomagent_rules import CORE_V1, PACKS, RuleContext, run_pack, validate
from bomagent_testing.data import kicad_project_paths


def item(line=1, refdes=("R1",), **kw) -> BomItem:
    data = {
        "line": line,
        "refdes": list(refdes),
        "quantity": len(refdes),
        "kind": "resistor",
        "value": "10k",
        "footprint": "Resistor_SMD:R_0603_1608Metric",
        "package": "0603",
        "mpn": "RC0603FR-0710KL",
        "manufacturer": "Yageo",
    }
    data.update(kw)
    return BomItem(**data)


def codes(report) -> set[str]:
    return {f.rule_id for f in report.findings}


def test_clean_bom_has_no_findings():
    report = validate([item()])
    assert report.ok
    assert report.findings == []
    assert report.pack == "core"
    assert report.version == "1.0.0"
    assert "schema.valid" in report.rules_run


def test_duplicate_refdes_across_lines():
    report = validate([item(1, ("R1", "R2")), item(2, ("R2",), value="1k")])
    dup = [f for f in report.findings if f.rule_id == "refdes.unique"]
    assert {tuple(f.refdes) for f in dup} == {("R2",)}
    assert not report.ok


def test_quantity_mismatch_and_schema_violation():
    bad = item().model_copy(update={"quantity": 3, "mpn": "x" * 3})
    bad_schema = item(2, ("R5",)).model_copy(update={"line": 0})
    report = validate([bad, bad_schema])
    assert {"quantity.matches_refdes", "schema.valid"} <= codes(report)


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"footprint": "", "package": None}, "footprint.present"),
        ({"mpn": ""}, "mpn.present"),
        ({"manufacturer": ""}, "manufacturer.present"),
        ({"value": "ten"}, "value.parsable"),
        ({"value": "5G"}, "value.range"),
        ({"value": "0R", "mpn": "RC0603JR-070RL"}, "value.zero_ohm"),
        ({"mpn": "RC0402FR-0710KL"}, "footprint.package_match"),
        ({"value": "10k 0805"}, "footprint.package_match"),
        ({"value": "100nF"}, "value.unit_kind"),
    ],
)
def test_single_rule_triggers(kw, code):
    assert code in codes(validate([item(**kw)]))


def test_dnp_and_test_points_are_exempt_from_mpn_and_footprint():
    report = validate(
        [
            item(dnp=True, mpn="", footprint="", package=None),
            item(
                2,
                ("TP1",),
                kind="test_point",
                value="TestPoint",
                mpn="",
                footprint="",
                package=None,
            ),
        ]
    )
    assert codes(report) == set()


def test_ic_part_numbers_with_size_like_digits_are_not_package_checked():
    ic = item(
        refdes=("U1",),
        kind="ic",
        value="LT1206",
        footprint="Package_SO:SOIC-8",
        package="SOIC-8",
        mpn="LT1206CS8",
        manufacturer="ADI",
    )
    assert "footprint.package_match" not in codes(validate([ic]))


def test_isolation_regex_and_lead_free_connector():
    parts = [
        item(
            1,
            ("U7",),
            kind="ic",
            value="PC817",
            footprint="DIP-4",
            package="DIP-4",
            mpn="PC817X",
            manufacturer="Sharp",
        ),
        item(
            2,
            ("J3",),
            kind="connector",
            value="Header lead-free",
            footprint="x",
            package=None,
            mpn="X1",
            manufacturer="Y",
        ),
    ]
    report = validate(parts, Requirements(applied_part=AppliedPart.BF))
    assert [f.refdes for f in report.findings if f.rule_id == "iec60601.isolation_barrier"] == [
        ["U7"]
    ]
    assert "iec60601.patient_connector" not in codes(report)
    assert "2 MOPP" not in report.findings[0].message  # battery device: no mains MOPP claim


def test_capacitor_voltage_rating():
    cap = item(
        refdes=("C1",),
        kind="capacitor",
        value="10u",
        mpn="",
        footprint="Capacitor_SMD:C_0603_1608Metric",
    )
    assert "capacitor.voltage_rating" in codes(validate([cap]))
    rated = cap.model_copy(update={"value": "10u/16V"})
    assert "capacitor.voltage_rating" not in codes(validate([rated]))
    with_mpn = cap.model_copy(update={"mpn": "CL10A106KP8NNNC", "manufacturer": "Samsung"})
    assert "capacitor.voltage_rating" not in codes(validate([with_mpn]))


def test_iec60601_flags_depend_on_requirements():
    parts = [
        item(
            1,
            ("J1",),
            kind="connector",
            value="Electrodes RA/LA/RL",
            footprint="x",
            package=None,
            mpn="22-23-2031",
            manufacturer="Molex",
        ),
        item(
            2,
            ("U5",),
            kind="ic",
            value="ADuM1201",
            footprint="SOIC-8",
            package="SOIC-8",
            mpn="ADUM1201ARZ",
            manufacturer="ADI",
        ),
        item(
            3,
            ("C9",),
            kind="capacitor",
            value="4n7 Y2",
            footprint="C_1812",
            package="1812",
            mpn="",
            manufacturer="",
        ),
        item(4, ("BT1",), kind="battery", value="LiPo 3.7V", footprint="x", package=None),
    ]
    none = validate(parts, Requirements())
    assert not any(
        f.severity == Severity.REVIEW and "isolation" in f.rule_id for f in none.findings
    )
    cf = validate(
        parts,
        Requirements(
            applied_part=AppliedPart.CF, defibrillation_proof=True, power_source=PowerSource.MAINS
        ),
    )
    got = codes(cf)
    assert {
        "iec60601.isolation_barrier",
        "iec60601.patient_connector",
        "iec60601.mains_fuse",
        "iec60601.y_capacitor",
        "iec60601.battery",
    } <= got
    patient = next(f for f in cf.findings if f.rule_id == "iec60601.patient_connector")
    assert "defibrillation" in patient.message
    assert all(f.rule_pack == "core" and f.rule_pack_version == "1.0.0" for f in cf.findings)


def test_mains_with_fuse_has_no_fuse_flag():
    parts = [item(1, ("F1",), kind="fuse", value="500mA", package=None, footprint="Fuse_1206")]
    report = validate(parts, Requirements(power_source=PowerSource.MAINS))
    assert "iec60601.mains_fuse" not in codes(report)


def test_run_pack_subset_and_registry():
    report = run_pack(
        CORE_V1,
        BomVersion(design_name="x", items=[item(mpn="")]),
        RuleContext(),
        only={"footprint.present"},
    )
    assert report.rules_run == ["footprint.present"]
    assert report.findings == []
    assert PACKS["core@1.0.0"] is CORE_V1
    assert CORE_V1.rule("mpn.present").severity == Severity.WARNING
    assert report.by_line() == {}


@pytest.mark.parametrize("project", ["ecg-frontend", "pulse-ox", "eeg-2ch"])
def test_fixture_projects_validate_without_errors(project):
    design = parse_files([FileRef.from_path(p) for p in kicad_project_paths(project)])
    report = validate(group_components(design))
    assert report.errors == [], report.errors
    # parts without MPN in the schematic are reported for the MPN selection step
    assert any(f.rule_id == "mpn.present" for f in report.findings) or project == "pulse-ox"
