from __future__ import annotations

import pytest

from bomagent_bom.packages import (
    package_from_footprint,
    package_from_part_number,
    package_from_text,
)
from bomagent_bom.refdes import compress, kind_of, sort_refdes, split_refdes


def test_natural_sort():
    assert sort_refdes(["R10", "R2", "R1", "C1", "R2"]) == ["C1", "R1", "R2", "R10"]


@pytest.mark.parametrize(
    ("ref", "kind"),
    [
        ("R1", "resistor"),
        ("C12", "capacitor"),
        ("U3", "ic"),
        ("J1", "connector"),
        ("FB1", "ferrite_bead"),
        ("TP4", "test_point"),
        ("LED2", "led"),
        ("RV1", "potentiometer"),
        ("ZZ9", "other"),
        ("U1A", "ic"),
    ],
)
def test_kind_from_prefix(ref, kind):
    assert kind_of(ref) == kind


def test_split_refdes_handles_unit_suffix_and_garbage():
    assert split_refdes("U1A") == ("U", 1, "A")
    assert split_refdes("weird") == ("weird", 0, "")


def test_compress_ranges():
    assert compress(["R1", "R2", "R3", "R5", "C1", "C2"]) == "C1, C2, R1-R3, R5"


@pytest.mark.parametrize(
    ("footprint", "pkg"),
    [
        ("Resistor_SMD:R_0603_1608Metric", "0603"),
        ("Capacitor_SMD:C_0402_1005Metric", "0402"),
        ("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "SOIC-8"),
        ("Package_TO_SOT_SMD:SOT-23", "SOT-23"),
        ("Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm", "QFN-20-1"),
        ("Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", None),
        ("Battery:BatteryHolder_Keystone_103_1x20mm", None),
        ("", None),
    ],
)
def test_package_from_footprint(footprint, pkg):
    assert package_from_footprint(footprint) == pkg


@pytest.mark.parametrize(
    ("mpn", "pkg"),
    [
        ("RC0603FR-0710KL", "0603"),
        ("GRM188R71H104KA93D", "0603"),
        ("GRM155R71C104KA88D", "0402"),
        ("CL10A106KP8NNNC", "0603"),
        ("C1608X7R1H104K080AA", "0603"),
        ("ERJ-3EKF1002V", "0603"),
        ("CRCW060310K0FKEA", "0603"),
        ("C0805C105K4RACTU", "0805"),
        ("C0603X5R0J104K030BC", "0201"),
        ("C0402X5R0J102K020BC", "01005"),
        ("AD8232ACPZ-R7", None),
        ("", None),
    ],
)
def test_package_from_part_number(mpn, pkg):
    assert package_from_part_number(mpn) == pkg


def test_package_from_text():
    assert package_from_text("100n 0402 X7R") == "0402"
    assert package_from_text("10.0603") is None
