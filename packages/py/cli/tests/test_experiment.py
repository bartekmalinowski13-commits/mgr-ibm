"""`bomagent experiment run`: the thesis experiment matrix on the fake provider."""

from __future__ import annotations

import csv
import json
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


def test_cli_command(tmp_path):
    out = tmp_path / "reports"
    res = CliRunner().invoke(
        app, ["experiment", "run", str(_config(tmp_path, repeats=1)), "--out", str(out)]
    )
    assert res.exit_code == 0, res.output
    assert (out / "pilot" / "report.md").exists()
    bad = CliRunner().invoke(app, ["experiment", "run", str(_config(tmp_path, variants=["C"]))])
    assert bad.exit_code != 0
