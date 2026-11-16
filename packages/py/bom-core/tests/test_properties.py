"""Property-based tests (Hypothesis) for value normalisation, designators and grouping.

QA-03: invariants that example tests cannot enumerate. Derandomised so CI is repeatable;
a failing example printed by Hypothesis should be promoted to a regular example test.
"""

from __future__ import annotations

import contextlib
import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bomagent_bom.grouping import group_components
from bomagent_bom.model import Component, ParsedDesign
from bomagent_bom.refdes import natural_key, sort_refdes, split_refdes
from bomagent_bom.values import (
    ValueParseError,
    normalize_value,
    parse_value,
    values_equivalent,
)

PROFILE = settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)

KINDS = st.sampled_from([None, "resistor", "capacitor", "inductor"])
# value-like text: digits, RKM marks, units, tolerance/voltage fragments, noise
_ALPHABET = "0123456789.,kKMmRruUnNpPµΩFHVv%±/ -+eXC"
VALUE_TEXT = st.text(alphabet=_ALPHABET, max_size=24)
RKM = st.builds(
    lambda i, mark, f: f"{i}{mark}{f}",
    st.integers(1, 999),
    st.sampled_from(["k", "K", "M", "R", "u", "n", "p"]),
    st.integers(0, 99),
)
REFDES = st.builds(
    lambda p, n: f"{p}{n}",
    st.sampled_from(["R", "C", "L", "D", "U", "Q", "J", "TP", "SW"]),
    st.integers(1, 400),
)


@PROFILE
@given(text=st.text(max_size=40), kind=KINDS)
def test_parse_value_only_raises_value_parse_error(text, kind):
    with contextlib.suppress(ValueParseError):
        parse_value(text, kind)


@PROFILE
@given(text=st.one_of(VALUE_TEXT, RKM), kind=KINDS)
def test_normalize_is_idempotent(text, kind):
    once = normalize_value(text, kind)
    if once is not None:
        assert normalize_value(once, kind) == once


@PROFILE
@given(a=st.one_of(VALUE_TEXT, RKM), b=st.one_of(VALUE_TEXT, RKM), kind=KINDS)
def test_values_equivalent_is_reflexive_and_symmetric(a, b, kind):
    assert values_equivalent(a, a, kind)
    assert values_equivalent(a, b, kind) == values_equivalent(b, a, kind)


@PROFILE
@given(refs=st.lists(REFDES, min_size=1, max_size=40))
def test_sort_refdes_is_deduplicated_sorted_and_stable(refs):
    ordered = sort_refdes(refs)
    assert ordered == sorted(set(refs), key=natural_key)
    assert sort_refdes(reversed(refs)) == ordered
    assert sort_refdes(ordered) == ordered


@PROFILE
@given(ref=REFDES)
def test_split_refdes_reassembles(ref):
    prefix, num, suffix = split_refdes(ref)
    assert f"{prefix}{num}{suffix}" == ref


_COMPONENT = st.builds(
    lambda ref, value, fp, dnp: Component(refdes=ref, value=value, footprint=fp, dnp=dnp),
    REFDES,
    st.sampled_from(["10k", "10K", "10 kΩ", "4k7", "100n", "0.1uF", "AD8232", ""]),
    st.sampled_from(["R_0603", "C_0402", ""]),
    st.booleans(),
)


def _design(components: list[Component]) -> ParsedDesign:
    return ParsedDesign(
        design_name="p", source_format="kicad", components=components, confidence=1.0
    )


@PROFILE
@given(components=st.lists(_COMPONENT, max_size=30, unique_by=lambda c: c.refdes))
def test_grouping_partitions_every_component_exactly_once(components):
    items = group_components(_design(components))
    grouped = [r for i in items for r in i.refdes]
    assert sorted(grouped) == sorted(c.refdes for c in components)
    assert all(i.quantity == len(i.refdes) for i in items)
    assert [i.line for i in items] == list(range(1, len(items) + 1))


@PROFILE
@given(
    components=st.lists(_COMPONENT, max_size=30, unique_by=lambda c: c.refdes),
    seed=st.integers(0, 2**32 - 1),
)
def test_grouping_is_independent_of_input_order(components, seed):
    shuffled = list(components)
    random.Random(seed).shuffle(shuffled)
    a = group_components(_design(components))
    b = group_components(_design(shuffled))
    assert [(i.refdes, i.value_normalized, i.dnp) for i in a] == [
        (i.refdes, i.value_normalized, i.dnp) for i in b
    ]
