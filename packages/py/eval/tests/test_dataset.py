"""TH-03: dataset hygiene and inter-rater agreement for hand-built reference BOMs."""

from __future__ import annotations

import math

import pytest

from bomagent_eval.agreement import AgreementReport, cohens_kappa, compare_verifiers
from bomagent_eval.dataset import (
    DatasetError,
    Stratum,
    parse_source_md,
    stratum_of,
    validate_dataset,
)
from bomagent_eval.reference import load_reference_csv

A = """Reference,Qty,Value,Footprint,Manufacturer,MPN
R1 R2,2,10k,R_0603,Yageo,RC0603FR-0710KL
C1,1,100n,C_0603,Murata,GRM188R71H104KA93D
U1,1,TLV9062,SOIC-8,TI,TLV9062IDR
"""
B_SAME = A
B_DIFF = """Reference,Qty,Value,Footprint,Manufacturer,MPN
R1 R2,2,10k,R_0603,Yageo,RC0603FR-0710KL
C1,1,100n,C_0805,Murata,GRM188R71H104KA93D
U1,1,TLV9062,SOIC-8,TI,TLV9061IDR
"""


def test_identical_verifiers_agree_perfectly():
    report = compare_verifiers(load_reference_csv(A), load_reference_csv(B_SAME))
    assert isinstance(report, AgreementReport)
    assert report.designators_compared == 4
    assert report.only_in_one == []
    assert all(f.agreement == 1.0 for f in report.fields.values())
    assert report.disagreements == []


def test_disagreements_are_listed_and_lower_agreement():
    report = compare_verifiers(load_reference_csv(A), load_reference_csv(B_DIFF))
    assert report.fields["value"].agreement == 1.0
    assert report.fields["footprint"].agreement == pytest.approx(3 / 4)
    assert report.fields["mpn"].agreement == pytest.approx(3 / 4)
    assert {(d.refdes, d.field) for d in report.disagreements} == {
        ("C1", "footprint"),
        ("U1", "mpn"),
    }
    assert report.fields["footprint"].kappa < 1.0


def test_designators_in_only_one_bom_are_reported():
    extra = A + "R9,1,1k,R_0603,Yageo,RC0603FR-071KL\n"
    report = compare_verifiers(load_reference_csv(A), load_reference_csv(extra))
    assert report.only_in_one == ["R9"]
    assert report.designators_compared == 4


def test_cohens_kappa_handles_chance_agreement_and_degenerate_input():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohens_kappa(["a", "a", "b", "b"], ["b", "b", "a", "a"]) == -1.0
    assert cohens_kappa(["a", "a", "a"], ["a", "a", "a"]) == 1.0  # one category, full agreement
    assert math.isnan(cohens_kappa([], []))
    with pytest.raises(ValueError, match="same length"):
        cohens_kappa(["a"], ["a", "b"])


def test_stratum_by_component_count():
    assert stratum_of(10) is Stratum.SMALL
    assert stratum_of(39) is Stratum.SMALL
    assert stratum_of(40) is Stratum.MEDIUM
    assert stratum_of(150) is Stratum.MEDIUM
    assert stratum_of(151) is Stratum.LARGE
    with pytest.raises(ValueError, match="at least one"):
        stratum_of(0)


GOOD_SOURCE = """# Source

- URL: https://github.com/example/board
- Commit: 86bb1f4
- Licence: CERN-OHL-S-2.0
- Retrieved: 2026-11-09
- Verifier 1: A. Author
- Verifier 2: B. Reviewer
"""


def test_source_md_is_parsed_and_validated():
    info = parse_source_md(GOOD_SOURCE)
    assert info.commit == "86bb1f4"
    assert info.licence == "CERN-OHL-S-2.0"
    assert info.verifiers == ["A. Author", "B. Reviewer"]
    with pytest.raises(DatasetError, match="Licence"):
        parse_source_md(GOOD_SOURCE.replace("- Licence: CERN-OHL-S-2.0\n", ""))
    with pytest.raises(DatasetError, match="Commit"):
        parse_source_md(GOOD_SOURCE.replace("86bb1f4", "main"))


def test_real_designs_need_two_distinct_verifiers_but_controls_do_not(tmp_path):
    real = tmp_path / "real-board"
    real.mkdir()
    (real / "SOURCE.md").write_text(GOOD_SOURCE.replace("- Verifier 2: B. Reviewer\n", ""))
    (real / "reference_bom.csv").write_text(A)
    with pytest.raises(DatasetError, match="two"):
        validate_dataset(real, role="real")
    validate_dataset(real, role="control")  # self-authored controls need no verifiers
    (real / "SOURCE.md").write_text(GOOD_SOURCE.replace("B. Reviewer", "A. Author"))
    with pytest.raises(DatasetError, match="distinct"):
        validate_dataset(real, role="real")
    (real / "SOURCE.md").write_text(GOOD_SOURCE)
    assert validate_dataset(real, role="real").stratum is Stratum.SMALL


def test_self_authored_fixtures_are_valid_controls():
    from bomagent_testing.data import KICAD_FIXTURES

    for project in ("ecg-frontend", "eeg-2ch", "pulse-ox"):
        entry = validate_dataset(KICAD_FIXTURES / project, role="control")
        assert entry.role == "control"
        assert entry.stratum is Stratum.SMALL
        assert entry.source is None
