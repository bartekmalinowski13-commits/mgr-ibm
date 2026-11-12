"""`bomagent experiment run`: the thesis experiment matrix on the fake provider."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from typer.testing import CliRunner

from bomagent_cli.experiment import ExperimentConfig, run_experiment
from bomagent_cli.main import app
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES


def _config(tmp_path: Path, **overrides) -> Path:
    data = {
        "name": "pilot",
        "designs": [str(KICAD_FIXTURES / "ecg-frontend")],
        "variants": ["A", "B"],
        "models": ["fake-closed"],
        "repeats": 2,
        "kb_dir": str(FIXTURES / "datasheets"),
        "seed": 11,
        "injection": {"errors": 4, "trials": 2},
    } | overrides
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_matrix_runs_and_writes_reproducible_artifacts(tmp_path):
    config = ExperimentConfig.from_file(_config(tmp_path))
    result = run_experiment(config, tmp_path / "out")
    out = tmp_path / "out" / "pilot"
    runs = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert len(runs) == 4  # 1 design x 2 variants x 1 model x 2 repeats
    assert {(r["variant"], r["repeat"]) for r in runs} == {("A", 0), ("A", 1), ("B", 0), ("B", 1)}
    assert all(r["status"] == "completed" for r in runs)
    assert all(0 <= r["metrics"]["line_f1"] <= 1 for r in runs)

    rows = list(csv.DictReader((out / "results.csv").open()))
    assert len(rows) == 4
    assert {"design", "variant", "model", "repeat", "line_f1", "llm_calls", "cost_eur"} <= set(
        rows[0]
    )

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["config"]["repeats"] == 2
    assert manifest["rule_pack"] == {"id": "core", "version": "1.0.0"}
    assert set(manifest["prompts"]) >= {"mpn_select", "extract_group", "compose", "validate"}
    assert all("+" in v for v in manifest["prompts"].values())  # version+sha8

    report = (out / "report.md").read_text()
    for heading in ("Configuration", "Results per variant", "A vs B (paired)", "Repeatability"):
        assert heading in report
    comparison = result.comparisons["fake-closed"]["line_f1"]
    # the unit of the paired test is the design (repetitions are averaged first):
    # repetitions of one design are not independent observations (no pseudoreplication)
    assert comparison.n == 1
    assert result.cells[("B", "fake-closed")].runs == 2


def test_validation_is_measured_on_injected_errors(tmp_path):
    result = run_experiment(ExperimentConfig.from_file(_config(tmp_path, repeats=1)), tmp_path)
    out = tmp_path / "pilot"
    trials = [json.loads(line) for line in (out / "injection.jsonl").read_text().splitlines()]
    # 1 design x 2 variants x 1 model x 2 trials; the same mutations for A and B (paired)
    assert len(trials) == 4
    a = [t for t in trials if t["variant"] == "A"]
    b = [t for t in trials if t["variant"] == "B"]
    assert [t["errors"] for t in a] == [t["errors"] for t in b]
    assert all(t["injected"] >= 1 and 0 <= t["detection_rate"] <= 1 for t in trials)
    assert all(set(t["by_kind"]) <= {e["kind"] for e in t["errors"]} for t in trials)
    comparison = result.injection_comparisons["fake-closed"]["detection_rate"]
    assert comparison.n == 1
    report = (out / "report.md").read_text()
    assert "Validation effectiveness (error injection)" in report
    assert "drop_footprint" in report or "quantity_off_by_one" in report


def test_figures_and_tables_for_the_thesis(tmp_path):
    run_experiment(ExperimentConfig.from_file(_config(tmp_path, repeats=1)), tmp_path)
    out = tmp_path / "pilot"
    for name in ("quality", "paired-line_f1", "cost", "detection"):
        svg = (out / "figures" / f"{name}-fake-closed.svg").read_text(encoding="utf-8")
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        assert root.find("{http://www.w3.org/2000/svg}title") is not None  # accessible name
        assert ">A<" in svg
        assert ">B<" in svg
        assert "#2a78d6" in svg
        assert "#eb6834" in svg
    variants = list(csv.DictReader((out / "tables" / "variants.csv").open()))
    assert {r["variant"] for r in variants} == {"A", "B"}
    assert {"metric", "mean", "ci_low", "ci_high", "n"} <= set(variants[0])
    paired = list(csv.DictReader((out / "tables" / "paired.csv").open()))
    assert {"metric", "n", "mean_a", "mean_b", "diff", "ci_low", "ci_high", "p_value"} <= set(
        paired[0]
    )
    kinds = list(csv.DictReader((out / "tables" / "detection_by_kind.csv").open()))
    assert {"variant", "model", "kind", "injected", "detected", "rate"} <= set(kinds[0])


def test_injection_can_be_switched_off(tmp_path):
    cfg = _config(tmp_path, repeats=1, variants=["B"], injection={"errors": 4, "trials": 0})
    result = run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    assert not (tmp_path / "pilot" / "injection.jsonl").exists()
    assert result.injection_comparisons == {}


def test_cli_command(tmp_path):
    out = tmp_path / "reports"
    res = CliRunner().invoke(
        app, ["experiment", "run", str(_config(tmp_path, repeats=1)), "--out", str(out)]
    )
    assert res.exit_code == 0, res.output
    assert (out / "pilot" / "report.md").exists()
    bad = CliRunner().invoke(app, ["experiment", "run", str(_config(tmp_path, variants=["C"]))])
    assert bad.exit_code != 0
