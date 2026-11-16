"""TH-08/TH-09: appendices and status page generated from a fake-provider run."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from bomagent_cli.experiment import ExperimentConfig, run_experiment
from bomagent_cli.main import app
from bomagent_cli.thesis_assets import TRACE_ROWS, repo_root, status_html, write_appendices
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("th")
    data = {
        "name": "pilot",
        "designs": [str(KICAD_FIXTURES / "ecg-frontend")],
        "models": ["fake-closed"],
        "repeats": 1,
        "kb_dir": str(FIXTURES / "datasheets"),
        "seed": 3,
        "injection": {"errors": 3, "trials": 1},
    }
    path = tmp / "e.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return run_experiment(ExperimentConfig.from_file(path), tmp / "out").out_dir


def test_appendices_are_generated_from_the_run(run_dir: Path) -> None:
    paths = write_appendices(run_dir)
    out = run_dir / "appendices"
    assert {p.name for p in paths} == {
        "dodatek-a-prompty.md",
        "dodatek-b-schemat-bom.json",
        "dodatek-c-uruchomienie.md",
        "tabela-pb-metryka-kod-test.md",
        "tabela-pb-metryka-kod-test.csv",
    }
    manifest = json.loads((run_dir / "manifest.json").read_text())
    a = (out / "dodatek-a-prompty.md").read_text()
    for pid, version in manifest["prompts"].items():
        assert f"`{pid}`" in a
        assert version in a
    assert "NIE" not in a  # recorded versions match the repository
    schema = json.loads((out / "dodatek-b-schemat-bom.json").read_text())
    assert schema["$schema"].startswith("https://json-schema.org/")
    c = (out / "dodatek-c-uruchomienie.md").read_text()
    assert manifest["commit"] in c
    assert "fake-closed" in c
    assert "experiment run" in c
    assert yaml.safe_load(c.split("```yaml\n")[1].split("```")[0])["seed"] == 3


def test_appendix_a_flags_a_prompt_changed_since_the_run(run_dir: Path, tmp_path: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    manifest["prompts"]["compose"] = "1+deadbeef"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "runs.jsonl").write_text("")
    write_appendices(tmp_path)
    assert "NIE" in (tmp_path / "appendices" / "dodatek-a-prompty.md").read_text()


def test_trace_table_points_at_existing_files(run_dir: Path) -> None:
    write_appendices(run_dir)
    root = repo_root()
    for _, _, code, test in TRACE_ROWS:
        assert (root / code).is_file(), code
        assert (root / test).is_file(), test
    table = run_dir / "appendices" / "tabela-pb-metryka-kod-test.csv"
    with table.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["research_question"] for r in rows} >= {"PB1", "PB2", "PB3", "H1"}


def test_status_page(run_dir: Path) -> None:
    page = status_html(run_dir)
    assert "2 of 2 planned runs recorded (complete)" in page  # 2 variants x 1 repeat
    assert "fake provider" in page
    assert "line_f1" in page
    assert "attempted_mpn_hallucination_rate" in page
    assert "<script" not in page
    assert "prefers-color-scheme" in page


def test_status_page_marks_incomplete_runs_and_escapes(run_dir: Path, tmp_path: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    manifest["config"]["name"] = "x<script>"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "runs.jsonl").write_text("")
    page = status_html(tmp_path)
    assert "INCOMPLETE" in page
    assert "<script>" not in page


def test_cli_commands(run_dir: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app, ["experiment", "appendices", str(run_dir), "--out", str(tmp_path / "a")]
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "a" / "dodatek-a-prompty.md").exists()
    res = runner.invoke(
        app, ["experiment", "status", str(run_dir), "--out", str(tmp_path / "s.html")]
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "s.html").read_text().startswith("<!doctype html>")
    bad = runner.invoke(app, ["experiment", "status", str(tmp_path)])
    assert bad.exit_code == 2
