"""`bomagent experiment run`: the thesis experiment matrix on the fake provider."""

from __future__ import annotations

import csv
import json
import math
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
    # TH-05: exact model ids and sampling settings are part of the manifest
    assert manifest["model_ids"] == {"fake-closed": "fake-closed"}
    assert manifest["sampling"]["temperature"] == 0.0
    assert manifest["sampling"]["seed"] == manifest["config"]["seed"]
    assert "not deterministic" in manifest["sampling"]["note"]
    # TH-02: the retrieval stack and the exact knowledge-base content are recorded
    retrieval = manifest["retrieval"]
    assert retrieval["retriever"] == "in-memory"
    assert retrieval["embedding"] == "hashing (feature hashing, non-semantic)"
    assert retrieval["reranker"] == "lexical"
    assert retrieval["kb_snapshot_id"].startswith("sha256:")
    assert retrieval["kb_files"] >= 1

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


def test_kb_snapshot_id_tracks_content(tmp_path):
    from bomagent_cli.experiment import kb_snapshot

    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"\x00")
    first = kb_snapshot(tmp_path)
    assert first == kb_snapshot(tmp_path)  # stable
    assert first[1] == 1  # only supported datasheet files count
    (tmp_path / "a.md").write_text("alpha!", encoding="utf-8")
    assert kb_snapshot(tmp_path)[0] != first[0]
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    assert kb_snapshot(tmp_path)[1] == 2


def test_beyond_rule_kinds_can_be_injected_and_reported_with_coverage(tmp_path):
    from bomagent_eval.injection import BEYOND_RULES_KINDS

    cfg = _config(
        tmp_path,
        repeats=1,
        injection={"errors": 6, "trials": 4, "kinds": list(BEYOND_RULES_KINDS)},
    )
    run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    out = tmp_path / "pilot"
    trials = [json.loads(line) for line in (out / "injection.jsonl").read_text().splitlines()]
    assert {e["kind"] for t in trials for e in t["errors"]} <= set(BEYOND_RULES_KINDS)
    assert all("false_alarms_by_rule" in t for t in trials)
    b = [t for t in trials if t["variant"] == "B"]
    assert sum(t["detected"] for t in b) == 0  # B's rules cannot see these classes
    report = (out / "report.md").read_text()
    assert "rule coverage" in report
    assert "| no |" in report
    header = (out / "tables" / "detection_by_kind.csv").read_text().splitlines()[0]
    assert "rule_covered" in header


def test_unknown_injection_kind_is_rejected(tmp_path):
    import pytest
    from pydantic import ValidationError

    cfg = _config(tmp_path, injection={"errors": 2, "trials": 1, "kinds": ["nonsense"]})
    with pytest.raises(ValidationError, match="nonsense"):
        ExperimentConfig.from_file(cfg)


def test_primary_family_has_holm_effect_size_and_cluster_sensitivity(tmp_path):
    from bomagent_cli.experiment import PRIMARY_METRICS

    result = run_experiment(ExperimentConfig.from_file(_config(tmp_path, repeats=2)), tmp_path)
    comps = result.comparisons["fake-closed"]
    assert set(PRIMARY_METRICS) == {"line_f1", "attempted_mpn_hallucination_rate", "cost_eur"}
    for metric in PRIMARY_METRICS:
        c = comps[metric]
        if c.n and not math.isnan(c.p_value):
            assert c.p_holm >= c.p_value  # adjustment never lowers p
            assert c.p_holm <= 1.0
    assert all(math.isnan(c.p_holm) for m, c in comps.items() if m not in PRIMARY_METRICS)
    assert any(not math.isnan(c.cluster_ci_low) for c in comps.values())
    out = tmp_path / "pilot"
    header = (out / "tables" / "paired.csv").read_text().splitlines()[0].split(",")
    assert {"effect_size", "p_holm", "cluster_ci_low", "cluster_ci_high", "primary"} <= set(header)
    report = (out / "report.md").read_text()
    assert "Holm" in report
    assert "d_z" in report


# --------------------------------------------------------------------------- review fixes


class _Chat:
    """Fake provider wrapper for the matrix: counts calls, can fail chosen calls."""

    def __init__(self, fail=None):
        from bomagent_agents.fake_responder import heuristic_responder
        from bomagent_llm.chat import FakeChat

        self.inner = FakeChat(heuristic_responder)
        self.fail = fail or (lambda request, n: None)
        self.n = 0

    async def complete(self, request):
        self.n += 1
        error = self.fail(request, self.n)
        if error is not None:
            raise error
        return await self.inner.complete(request)


def _patch_chat(monkeypatch, chat):
    import bomagent_cli.main as main_mod

    monkeypatch.setattr(main_mod, "build_chat", lambda model, cassettes: chat)
    return chat


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_failed_validator_calls_are_failures_not_misses(tmp_path, monkeypatch):
    """I1: a validator call that fails (model error) is recorded with its status and kept
    out of the rates; the same rule for both variants; every validate call has its own
    budget (no shared wall clock across baseline and trials)."""
    from bomagent_llm.chat import LlmError

    validates = {"n": 0}

    def fail(request, n):
        if request.prompt_id == "validate":
            validates["n"] += 1
            if validates["n"] == 2:  # A: baseline ok, first trial fails
                return LlmError("gateway timed out", billing="estimated")
        return None

    _patch_chat(monkeypatch, _Chat(fail))
    cfg = _config(tmp_path, repeats=1, injection={"errors": 4, "trials": 2})
    result = run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    trials = _lines(tmp_path / "pilot" / "injection.jsonl")
    a = sorted((t for t in trials if t["variant"] == "A"), key=lambda t: t["trial"])
    b = [t for t in trials if t["variant"] == "B"]
    assert [t["status"] for t in a] == ["failed", "completed"]
    assert a[0]["detection_rate"] is None
    assert a[0]["false_alarm_rate"] is None
    assert a[0]["detected"] is None
    assert a[0]["by_kind"] == {}
    assert all(t["status"] == "completed" for t in b)
    # the failed trial does not count as a miss: A's mean is over completed trials only
    comparison = result.injection_comparisons["fake-closed"]["detection_rate"]
    assert comparison.mean_a == a[1]["detection_rate"]
    report = (tmp_path / "pilot" / "report.md").read_text()
    assert "failed trials" in report


def test_a_failed_baseline_excludes_the_design_from_the_rates(tmp_path, monkeypatch):
    from bomagent_llm.chat import LlmError

    def fail(request, n):  # only the injection's validator calls, not the full runs
        if request.metadata["run_id"].startswith("validation-"):
            return LlmError("gateway returned 500", billing="unbilled")
        return None

    chat = _patch_chat(monkeypatch, _Chat(fail))
    cfg = _config(tmp_path, repeats=1, injection={"errors": 4, "trials": 3})
    result = run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    trials = _lines(tmp_path / "pilot" / "injection.jsonl")
    a = [t for t in trials if t["variant"] == "A"]
    assert len(a) == 3
    assert {t["status"] for t in a} == {"baseline_failed"}
    assert all(t["detection_rate"] is None for t in a)
    comparison = result.injection_comparisons["fake-closed"]["detection_rate"]
    assert math.isnan(comparison.mean_a)
    # nothing is validated against a failed baseline: only the baseline call was made
    validate_calls = [r for r in chat.inner.calls if r.prompt_id == "validate"]
    assert all(not r.metadata["run_id"].startswith("validation-") for r in validate_calls)
    assert chat.n - len(chat.inner.calls) == 1  # one failed call: the baseline


def test_run_budget_is_configured_consistent_and_in_the_manifest(tmp_path, monkeypatch):
    """I2: the budget that decides outcomes is part of the configuration, reaches every run
    and is recorded; a run timeout shorter than the per-call budgets is refused."""
    import pytest
    from pydantic import ValidationError

    from bomagent_agents import contracts
    from bomagent_cli.experiment import minimum_run_timeout_s
    from bomagent_llm.catalog import load_catalog

    seen = []
    real_init = contracts.Budget.__init__

    def spy(self, config, *args, **kwargs):
        seen.append(config)
        real_init(self, config, *args, **kwargs)

    monkeypatch.setattr(contracts.Budget, "__init__", spy)
    budget = {"timeout_s": 4000, "max_llm_calls": 150, "concurrency": 4}
    cfg = _config(tmp_path, repeats=1, budget=budget, injection={"errors": 2, "trials": 1})
    run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    assert seen
    assert all((c.timeout_s, c.max_llm_calls, c.concurrency) == (4000, 150, 4) for c in seen)
    manifest = json.loads((tmp_path / "pilot" / "manifest.json").read_text())
    recorded = manifest["budget"]
    assert recorded["timeout_s"] == 4000
    assert {"max_llm_calls", "max_total_tokens", "kb_k", "max_repair_iterations"} <= set(recorded)
    assert manifest["minimum_run_timeout_s"]["fake-closed"] <= 4000

    # the pre-registered default fits the slowest enabled model's per-call budgets
    default = ExperimentConfig.from_file(_config(tmp_path)).budget.timeout_s
    assert default >= minimum_run_timeout_s(load_catalog().get("mistral-large-eu"))
    with pytest.raises(ValidationError):
        ExperimentConfig.from_file(_config(tmp_path, budget={"timeout_s": -1}))
    with pytest.raises(ValueError, match="timeout"):
        run_experiment(
            ExperimentConfig.from_file(
                _config(tmp_path, models=["mistral-large-eu"], budget={"timeout_s": 1200})
            ),
            tmp_path / "small",
        )


def test_an_exception_in_one_run_is_recorded_and_the_matrix_goes_on(tmp_path, monkeypatch):
    """I5: an unexpected exception is a reported run (status error, type, spend so far),
    not the end of the matrix."""

    failed_run = []

    def fail(request, n):
        if n == 3:
            failed_run.append(request.metadata["run_id"])
            return TypeError("content is a list")
        return None

    chat = _patch_chat(monkeypatch, _Chat(fail))
    cfg = _config(tmp_path, repeats=2, variants=["A"], injection={"errors": 2, "trials": 0})
    result = run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    runs = _lines(tmp_path / "pilot" / "runs.jsonl")
    assert len(runs) == 2
    errored = [r for r in runs if r["status"] == "error"]
    assert len(errored) == 1
    assert errored[0]["error"] == "TypeError"
    # the spend of every call the failed run got answered (concurrent branches included)
    answered = [r for r in chat.inner.calls if r.metadata["run_id"] == failed_run[0]]
    assert errored[0]["spent"]["llm_calls"] == len(answered) >= 2
    assert errored[0]["metrics"] == {}
    assert result.cells[("A", "fake-closed")].statuses["error"] == 1
    assert "error" in (tmp_path / "pilot" / "report.md").read_text()


def test_a_crashed_matrix_resumes_without_rerunning_paid_cells(tmp_path, monkeypatch):
    """I5/M4: results are persisted as they finish and the manifest before the first run;
    a restart skips finished runs and trials and never repeats a paid call."""
    import pytest

    class Crash(BaseException):  # like a killed process: nothing catches it
        pass

    config = ExperimentConfig.from_file(
        _config(tmp_path, repeats=2, injection={"errors": 3, "trials": 2})
    )
    out = tmp_path / "out" / "pilot"
    first = _patch_chat(monkeypatch, _Chat(lambda r, n: Crash() if n == 40 else None))
    with pytest.raises(Crash):
        run_experiment(config, tmp_path / "out")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["config"]["name"] == "pilot"
    assert isinstance(manifest["dirty"], bool)
    assert _lines(out / "runs.jsonl")
    paid_before = first.n - 1  # the crashing call was never answered

    second = _patch_chat(monkeypatch, _Chat())
    result = run_experiment(config, tmp_path / "out")
    runs = _lines(out / "runs.jsonl")
    keys = [(r["design_dir"], r["variant"], r["model"], r["repeat"]) for r in runs]
    assert len(keys) == len(set(keys)) == 4
    trials = _lines(out / "injection.jsonl")
    tkeys = [(t["design_dir"], t["variant"], t["model"], t["trial"]) for t in trials]
    assert len(tkeys) == len(set(tkeys)) == 4
    assert len(result.records) == 4
    assert json.loads((out / "manifest.json").read_text())["resumed"]
    # a fresh, uninterrupted matrix needs exactly the calls of both attempts together,
    # minus the cell cut off by the crash (its answered calls are paid again)
    fresh = _patch_chat(monkeypatch, _Chat())
    run_experiment(config, tmp_path / "fresh")
    assert paid_before + second.n >= fresh.n
    assert second.n < fresh.n
    # a third start has nothing left to do
    third = _patch_chat(monkeypatch, _Chat())
    run_experiment(config, tmp_path / "out")
    assert third.n == 0
    # a different matrix in the same directory is refused
    with pytest.raises(ValueError, match="different configuration"):
        run_experiment(ExperimentConfig.from_file(_config(tmp_path, repeats=3)), tmp_path / "out")


def test_billing_flags_are_counted_per_run_and_reported(tmp_path, monkeypatch):
    """I3: timed-out (estimated) and unbilled calls are visible per run and per variant."""
    from bomagent_bom.model import Usage
    from bomagent_llm.chat import LlmError

    def fail(request, n):
        if request.prompt_id == "mpn_select" and n % 3 == 0:
            return LlmError("gateway timed out", Usage(llm_calls=1), billing="estimated")
        return None

    _patch_chat(monkeypatch, _Chat(fail))
    cfg = _config(tmp_path, repeats=1, injection={"errors": 2, "trials": 0})
    run_experiment(ExperimentConfig.from_file(cfg), tmp_path)
    runs = _lines(tmp_path / "pilot" / "runs.jsonl")
    assert sum(r["billing"]["estimated_calls"] for r in runs) >= 1
    assert all(r["billing"]["unbilled_calls"] == 0 for r in runs)
    report = (tmp_path / "pilot" / "report.md").read_text()
    assert "estimated usage" in report


def test_designs_with_the_same_name_are_rejected(tmp_path):
    """M10: two directories parsing to one design name would merge two statistical units."""
    import shutil

    import pytest

    copy = tmp_path / "copy" / "ecg-frontend"
    shutil.copytree(KICAD_FIXTURES / "ecg-frontend", copy)
    cfg = _config(tmp_path, designs=[str(KICAD_FIXTURES / "ecg-frontend"), str(copy)])
    with pytest.raises(ValueError, match="same design name"):
        run_experiment(ExperimentConfig.from_file(cfg), tmp_path / "out")
