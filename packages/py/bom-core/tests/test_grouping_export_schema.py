from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bomagent_bom.export import to_csv, to_json
from bomagent_bom.grouping import group_components, renumber
from bomagent_bom.model import BomItem, BomVersion, Component, ParsedDesign, Usage
from bomagent_bom.schema import bom_item_json_schema, bom_json_schema, dump

SCHEMA_FILE = Path(__file__).parents[1] / "schemas" / "bom.schema.json"


def _design(*components: Component) -> ParsedDesign:
    return ParsedDesign(
        design_name="t", source_format="kicad", components=list(components), confidence=1.0
    )


def _c(ref, value="", fp="", **fields):
    return Component(refdes=ref, value=value, footprint=fp, fields=fields)


def test_identical_parts_are_grouped_regardless_of_value_notation():
    d = _design(
        _c("R2", "4k7", "Resistor_SMD:R_0603_1608Metric", MPN="RC0603FR-074K7L"),
        _c("R10", "4.7k", "Resistor_SMD:R_0603_1608Metric", MPN="RC0603FR-074K7L"),
        _c("R1", "10k", "Resistor_SMD:R_0603_1608Metric"),
        _c("C1", "100n", "Capacitor_SMD:C_0402_1005Metric"),
    )
    items = group_components(d)
    assert [i.refdes for i in items] == [["C1"], ["R1"], ["R2", "R10"]]
    r = items[2]
    assert r.quantity == 2
    assert r.value_normalized == "4.7 kΩ"
    assert r.package == "0603"
    assert r.mpn == "RC0603FR-074K7L"
    assert r.provenance["quantity"].kind == "rule"
    assert r.provenance["mpn"].kind == "parser"
    assert [i.line for i in items] == [1, 2, 3]


def test_different_ratings_are_not_merged():
    d = _design(
        _c("C1", "100n 16V", "C_0603"),
        _c("C2", "100n/50V X7R", "C_0603"),
        _c("C3", "100nF 50V X7R", "C_0603"),
        _c("R1", "10k 5%", "R_0603"),
        _c("R2", "10k 0.1%", "R_0603"),
    )
    assert [i.refdes for i in group_components(d)] == [["C1"], ["C2", "C3"], ["R1"], ["R2"]]


def test_dnp_and_different_footprints_split_lines():
    d = _design(
        _c("R1", "10k", "R_0603"),
        _c("R2", "10k", "R_0805"),
        Component(refdes="R3", value="10k", footprint="R_0603", dnp=True),
    )
    items = group_components(d)
    assert len(items) == 3
    assert [i.dnp for i in items] == [False, False, True]


def test_power_symbols_and_excluded_parts_are_skipped():
    d = _design(
        _c("#PWR01", "GND"),
        Component(refdes="H1", value="MountingHole", in_bom=False),
        _c("U1", "AD8232"),
    )
    assert [i.refdes for i in group_components(d)] == [["U1"]]


def test_bom_item_rejects_duplicate_refdes_and_sorts():
    with pytest.raises(ValidationError):
        BomItem(line=1, refdes=["R1", "R1"], quantity=2)
    assert BomItem(line=1, refdes=["R10", "R2"], quantity=2).refdes == ["R2", "R10"]


def test_renumber():
    items = [BomItem(line=5, refdes=["R2"], quantity=1), BomItem(line=1, refdes=["C1"], quantity=1)]
    assert [(i.line, i.refdes[0]) for i in renumber(items)] == [(1, "C1"), (2, "R2")]


def test_csv_export_neutralises_formulas():
    bom = BomVersion(
        design_name="t",
        items=[BomItem(line=1, refdes=["R1", "R2", "R3"], quantity=3, value="=HYPERLINK(1)")],
    )
    rows = list(csv.reader(io.StringIO(to_csv(bom, compact_refdes=True))))
    assert rows[0][0] == "Line"
    assert rows[1][2] == "R1-R3"
    assert rows[1][3].startswith("'=")


def test_json_export_roundtrip():
    bom = BomVersion(design_name="t", items=[BomItem(line=1, refdes=["U1"], quantity=1)])
    again = BomVersion.model_validate_json(to_json(bom))
    assert again.items[0].refdes == ["U1"]
    assert again.total_parts == 1
    assert again.refdes_index()["U1"].line == 1


def test_usage_addition():
    u = Usage(llm_calls=1, input_tokens=10, cost_eur=0.1) + Usage(llm_calls=2, output_tokens=5)
    assert (u.llm_calls, u.input_tokens, u.output_tokens) == (3, 10, 5)


def test_committed_json_schema_is_current():
    # regenerate: uv run python -m bomagent_bom.schema > <bom-core>/schemas/bom.schema.json
    assert json.loads(SCHEMA_FILE.read_text()) == json.loads(dump(bom_json_schema()))
    assert bom_item_json_schema()["properties"]["refdes"]["minItems"] == 1
