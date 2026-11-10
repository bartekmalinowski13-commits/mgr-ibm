from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from bomagent_bom.values import (
    Quantity,
    ValueParseError,
    format_quantity,
    normalize_value,
    parse_quantity,
    parse_value,
    values_equivalent,
)


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("4k7", "resistor", "4.7 kΩ"),
        ("4K7", "resistor", "4.7 kΩ"),
        ("4.7k", "resistor", "4.7 kΩ"),
        ("4700", "resistor", "4.7 kΩ"),
        ("10k", "resistor", "10 kΩ"),
        ("10 kΩ", None, "10 kΩ"),
        ("10kohm", None, "10 kΩ"),
        ("2.2 kOhm", None, "2.2 kΩ"),
        ("1R0", None, "1 Ω"),
        ("1R", None, "1 Ω"),
        ("0R", None, "0 Ω"),
        ("R47", None, "470 mΩ"),
        ("4R7", "inductor", "4.7 µH"),
        ("4R7", "capacitor", "4.7 pF"),
        ("4.7 UF", "capacitor", "4.7 µF"),
        ("47 PF", "capacitor", "47 pF"),
        ("0.1 MFD", "capacitor", "100 nF"),
        ("2.2 MEG", "resistor", "2.2 MΩ"),
        ("4.7 UH", "inductor", "4.7 µH"),
        ("10 k\u2126", None, "10 kΩ"),
        ("6V3", None, "6.3 V"),
        ("1mF", None, "1 mF"),
        ("1M5", "resistor", "1.5 MΩ"),
        ("100M", "resistor", "100 MΩ"),
        ("100n", "capacitor", "100 nF"),
        ("100nF", None, "100 nF"),
        ("0.1uF", None, "100 nF"),
        ("0,1µF", None, "100 nF"),
        ("4u7", "capacitor", "4.7 µF"),
        ("2n2", "capacitor", "2.2 nF"),
        ("10p", "capacitor", "10 pF"),
        ("1000pF", None, "1 nF"),
        ("10uH", None, "10 µH"),
        ("3.3V", None, "3.3 V"),
        ("16MHz", None, "16 MHz"),
    ],
)
def test_normalize_examples(text, kind, expected):
    assert normalize_value(text, kind) == expected


@pytest.mark.parametrize("text", ["AD8232", "LM358", "MAX30102", "1N4148", "BAT54S", "", "DNP"])
def test_non_numeric_values_are_not_normalised(text):
    assert normalize_value(text, "resistor") is None


def test_attributes_are_extracted():
    pv = parse_value("100n/50V X7R 10%", "capacitor")
    assert format_quantity(pv.quantity) == "100 nF"
    assert pv.voltage_rating == Quantity(Decimal("50"), "V")
    assert pv.tolerance_percent == Decimal("10")
    assert pv.extra == ("X7R",)


def test_duplicate_unit_token_is_ignored():
    pv = parse_value("10u 10uF 16V", "capacitor")
    assert pv.extra == ()
    assert pv.voltage_rating is not None


def test_bare_rkm_without_kind_is_ambiguous():
    with pytest.raises(ValueParseError):
        parse_quantity("4u7")


@pytest.mark.parametrize(
    "bad",
    ["", "  ", "k10", "10xF", "/", "1,000pF", "2,200uF", "1,500", "1E3", "10MF", "10 parsecs"],
)
def test_invalid_values_raise(bad):
    with pytest.raises(ValueParseError):
        parse_value(bad, "resistor")


def test_unknown_words_after_a_unit_are_kept_as_extra():
    pv = parse_value("10k thin-film", "resistor")
    assert format_quantity(pv.quantity) == "10 kΩ"
    assert pv.extra == ("thin-film",)


@pytest.mark.parametrize("text", ["10k 1 %", "10k ±1%", "10k +/-1%", "10k ± 1 %"])
def test_tolerance_notations(text):
    assert parse_value(text, "resistor").tolerance_percent == Decimal("1")


def test_rkm_voltage_attribute():
    pv = parse_value("100n/6V3", "capacitor")
    assert pv.voltage_rating == Quantity(Decimal("6.3"), "V")


def test_comma_separates_attributes_but_not_decimals():
    assert parse_value("100n,50V", "capacitor").voltage_rating is not None
    assert format_quantity(parse_value("4,7k", "resistor").quantity) == "4.7 kΩ"


def test_equivalence_of_notations():
    assert values_equivalent("4k7", "4700", "resistor")
    assert values_equivalent("100n", "0.1uF", "capacitor")
    assert not values_equivalent("10k", "1k", "resistor")
    assert values_equivalent("AD8232", "ad8232")


_PREFIXED = st.builds(
    lambda m, e: Decimal(m).scaleb(e),
    st.integers(min_value=1, max_value=999),
    st.sampled_from([-12, -9, -6, -3, 0, 3, 6]),
)


@given(value=_PREFIXED, unit=st.sampled_from(["Ω", "F", "H"]))
def test_format_parse_roundtrip(value, unit):
    # mega-farad / mega-henry do not exist in BOMs and "MF" is rejected as ambiguous
    assume(not (unit in {"F", "H"} and value >= 1000))
    q = Quantity(value, unit)
    text = format_quantity(q)
    back = parse_quantity(text)
    assert back.unit == unit
    assert back.value == value


@given(
    st.integers(min_value=1, max_value=9),
    st.integers(min_value=0, max_value=9),
    st.sampled_from(["k", "M", "R"]),
)
def test_rkm_equals_decimal_notation(i, f, mark):
    rkm = f"{i}{mark}{f}"
    dec = f"{i}.{f}{'' if mark == 'R' else mark}"
    assert values_equivalent(rkm, dec, "resistor")
