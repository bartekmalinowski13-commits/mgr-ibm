"""Thesis experiment (M8): variants {A, B} x models x designs x repetitions.

Every run is scored against the design's reference BOM with the same metrics as the
product (``bomagent_eval``). The output directory holds everything chapter 6/7 needs
and everything needed to reproduce it:

* ``runs.jsonl`` - one record per run (metrics, usage, status, design, variant, model);
* ``results.csv`` - the same, flat, for spreadsheets and plotting;
* ``report.md`` - configuration, per-variant results with 95 % bootstrap intervals,
  paired A-vs-B comparisons (permutation test), repeatability;
* ``manifest.json`` - configuration, commit, prompt versions (``version+sha8``), rule
  pack, model catalogue entries, seeds.

Pairing: per model, variant A and B are compared per design, each design contributing
the mean over its repetitions (repetitions measure stability; they are not independent
samples - no pseudoreplication). Only the fake provider runs without credentials; real
models go through the LLM gateway configured in the environment and must be enabled in
the catalogue.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
import yaml
from pydantic import BaseModel, Field

from bomagent_cad import parse_files
from bomagent_cli.experiment_figures import Estimate, bar_panels, dot_interval_chart, slope_chart
from bomagent_eval.experiment_stats import PairedComparison, bootstrap_ci, compare_paired
from bomagent_eval.metrics import evaluate
from bomagent_eval.reference import load_reference
from bomagent_eval.stats import pairwise_agreement

MISSING = "n/a"
experiment_app = typer.Typer(help="Thesis experiment: variant A vs B on the evaluation set.")

PROMPT_IDS = ["extract_group", "mpn_select", "compose", "validate", "repair", "claude_agent_sdk"]
#: metrics compared between variants; direction: +1 = higher is better, -1 = lower is better
KEY_METRICS: dict[str, int] = {
    "line_f1": 1,
    "line_precision": 1,
    "line_recall": 1,
    "designator_f1": 1,
    "acc_mpn": 1,
    "acc_value": 1,
    "mpn_coverage": 1,
    "mpn_out_of_reference_rate": -1,
    "mpn_hallucination_rate": -1,
    "llm_calls": -1,
    "input_tokens": -1,
    "output_tokens": -1,
    "cost_eur": -1,
    "wall_time_s": -1,
}


Variant = Literal["A", "B"]
#: validation metrics on injected errors; direction as in KEY_METRICS
INJECTION_METRICS: dict[str, int] = {"detection_rate": 1, "false_alarm_rate": -1}


class InjectionConfig(BaseModel):
    """Validation effectiveness: known errors injected into each reference BOM."""

    errors: int = Field(default=5, ge=1, le=20)
    #: different mutations per design (0 switches the measurement off)
    trials: int = Field(default=3, ge=0, le=50)


class ExperimentConfig(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    designs: list[Path] = Field(min_length=1)
    variants: list[Variant] = Field(default=["A", "B"], min_length=1)
    models: list[str] = Field(default_factory=lambda: ["fake-closed"], min_length=1)
    repeats: int = Field(default=3, ge=1, le=50)
    kb_dir: Path = Path("evals/fixtures/datasheets")
    cassettes: Path | None = None
    seed: int = 0
    runtimes: dict[Variant, str] = Field(default_factory=dict)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)

    @classmethod
    def from_file(cls, path: Path) -> ExperimentConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class Cell:
    """Results of one (variant, model) combination."""

    runs: int = 0
    metrics: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    statuses: dict[str, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class ExperimentResult:
    out_dir: Path
    records: list[dict[str, Any]]
    cells: dict[tuple[str, str], Cell]
    comparisons: dict[str, dict[str, PairedComparison]]
    repeatability: dict[tuple[str, str], float]
    injection_records: list[dict[str, Any]] = field(default_factory=list)
    injection_comparisons: dict[str, dict[str, PairedComparison]] = field(default_factory=dict)


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _manifest(config: ExperimentConfig) -> dict[str, Any]:
    from bomagent_agents.prompts import load_prompt
    from bomagent_llm.catalog import load_catalog
    from bomagent_rules.core_v1 import PACK_VERSION

    catalog = load_catalog()
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "commit": _commit(),
        "config": json.loads(config.model_dump_json()),
        "prompts": {p: load_prompt(p).full_version for p in PROMPT_IDS},
        "rule_pack": {"id": "core", "version": PACK_VERSION},
        "models": {m: catalog.get(m).model_dump(mode="json") for m in config.models},
    }


async def _run_one(
    design: Any, variant: Variant, model: str, config: ExperimentConfig
) -> tuple[Any, set[str]]:
    from bomagent_agents.contracts import RunConfig, RunInput
    from bomagent_agents.registry import context_factory, runtime_for
    from bomagent_agents.retrieval import InMemoryRetriever
    from bomagent_bom.model import Requirements
    from bomagent_cli.main import build_chat

    retriever = await InMemoryRetriever.from_directory(config.kb_dir)
    chat = build_chat(model, config.cassettes)
    runtime = runtime_for(
        variant, context_factory(chat, retriever), runtime=config.runtimes.get(variant)
    )
    result = await runtime.run(
        RunInput(
            design=design,
            requirements=Requirements(),
            config=RunConfig(variant=variant, model_id=model),
        )
    )
    return result, await retriever.known_mpns()


async def _inject_one(
    design: str, reference: list[Any], variant: Variant, model: str, config: ExperimentConfig
) -> list[dict[str, Any]]:
    """Validator of ``variant`` on ``trials`` mutated copies of the reference BOM.

    The mutation of trial ``t`` depends only on the seed and ``t``, so A and B review
    exactly the same faulty BOMs (paired). New findings are counted against the
    validator's own findings on the clean reference (baseline)."""
    from bomagent_agents.contracts import RunConfig
    from bomagent_agents.retrieval import InMemoryRetriever
    from bomagent_agents.validation import validate_bom, validation_context
    from bomagent_bom.model import Requirements
    from bomagent_cli.main import build_chat
    from bomagent_eval.injection import detection_report, inject_errors

    retriever = await InMemoryRetriever.from_directory(config.kb_dir)
    ctx = validation_context(
        build_chat(model, config.cassettes),
        retriever,
        RunConfig(variant=variant, model_id=model),
        Requirements(),
    )
    baseline = await validate_bom(variant, ctx, reference)
    out = []
    for trial in range(config.injection.trials):
        mutated, errors = inject_errors(
            reference, n=config.injection.errors, seed=config.seed * 1009 + trial
        )
        if not errors:
            continue
        report = detection_report(errors, await validate_bom(variant, ctx, mutated), baseline)
        out.append(
            {
                "design": design,
                "variant": variant,
                "model": model,
                "trial": trial,
                "errors": [{"kind": e.kind, "line": e.line, "refdes": e.refdes} for e in errors],
                "injected": report.injected,
                "detected": report.detected,
                "new_findings": report.new_findings,
                "false_alarms": report.false_alarms,
                "detection_rate": report.detection_rate,
                "false_alarm_rate": report.false_alarm_rate,
                "by_kind": {k: list(v) for k, v in report.by_kind.items()},
            }
        )
    return out


def run_experiment(config: ExperimentConfig, out_root: Path) -> ExperimentResult:
    from bomagent_cli.main import collect_files

    out = out_root / config.name
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    injection_records: list[dict[str, Any]] = []
    boms: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for design_dir in config.designs:
        design = parse_files(collect_files([design_dir]))
        reference = load_reference(design_dir / "reference_bom.csv")
        design_mpns = {c.field("MPN") for c in design.components} - {""}
        for model in config.models:
            for variant in config.variants:
                if config.injection.trials:
                    injection_records += asyncio.run(
                        _inject_one(design.design_name, reference, variant, model, config)
                    )
                for rep in range(config.repeats):
                    result, known = asyncio.run(_run_one(design, variant, model, config))
                    report = evaluate(
                        result.bom,
                        reference,
                        known_mpns=known,
                        design_mpns=design_mpns,
                        design=design.design_name,
                        variant=variant,
                        model=model,
                    )
                    boms[(design.design_name, variant, model)].append(result.bom)
                    records.append(
                        {
                            "design": design.design_name,
                            "variant": variant,
                            "model": model,
                            "repeat": rep,
                            "runtime": result.runtime,
                            "status": result.status,
                            "metrics": {
                                k: (None if math.isnan(v) else v)
                                for k, v in report.summary().items()
                            },
                        }
                    )

    cells: dict[tuple[str, str], Cell] = defaultdict(Cell)
    for r in records:
        cell = cells[(r["variant"], r["model"])]
        cell.runs += 1
        cell.statuses[r["status"]] += 1
        for k, v in r["metrics"].items():
            cell.metrics[k].append(math.nan if v is None else float(v))

    comparisons: dict[str, dict[str, PairedComparison]] = {}
    if {"A", "B"} <= set(config.variants):
        for model in config.models:
            designs = sorted({r["design"] for r in records if r["model"] == model})
            comparisons[model] = {}
            for metric in KEY_METRICS:
                a = [_design_mean(records, d, "A", model, metric) for d in designs]
                b = [_design_mean(records, d, "B", model, metric) for d in designs]
                comparisons[model][metric] = compare_paired(a, b, seed=config.seed)

    repeatability = {
        (v, m): statistics.fmean(
            pairwise_agreement(runs) for (d, v2, m2), runs in boms.items() if (v2, m2) == (v, m)
        )
        for (v, m) in cells
    }
    injection_comparisons: dict[str, dict[str, PairedComparison]] = {}
    if injection_records and {"A", "B"} <= set(config.variants):
        for model in config.models:
            designs = sorted({r["design"] for r in injection_records if r["model"] == model})
            injection_comparisons[model] = {
                metric: compare_paired(
                    [_injection_mean(injection_records, d, "A", model, metric) for d in designs],
                    [_injection_mean(injection_records, d, "B", model, metric) for d in designs],
                    seed=config.seed,
                )
                for metric in INJECTION_METRICS
            }
    result = ExperimentResult(
        out,
        records,
        dict(cells),
        comparisons,
        repeatability,
        injection_records,
        injection_comparisons,
    )
    _write(result, config)
    return result


def _design_mean(
    records: list[dict[str, Any]], design: str, variant: str, model: str, metric: str
) -> float:
    """Mean of a metric over the repetitions of one design (the statistical unit)."""
    values = [
        float(r["metrics"][metric])
        for r in records
        if (r["design"], r["variant"], r["model"]) == (design, variant, model)
        and r["metrics"].get(metric) is not None
    ]
    return statistics.fmean(values) if values else math.nan


def _injection_mean(
    records: list[dict[str, Any]], design: str, variant: str, model: str, metric: str
) -> float:
    values = [
        float(r[metric])
        for r in records
        if (r["design"], r["variant"], r["model"]) == (design, variant, model)
    ]
    return statistics.fmean(values) if values else math.nan


def _fmt(v: float, metric: str) -> str:
    if math.isnan(v):
        return MISSING
    if metric in {"llm_calls", "input_tokens", "output_tokens"}:
        return f"{v:,.0f}".replace(",", " ")
    if metric == "cost_eur":
        return f"{v:.4f}"
    if metric == "wall_time_s":
        return f"{v:.2f}"
    return f"{v:.3f}"


def _write(result: ExperimentResult, config: ExperimentConfig) -> None:
    out = result.out_dir
    with (out / "runs.jsonl").open("w", encoding="utf-8") as f:
        for r in result.records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    metric_names = sorted({k for r in result.records for k in r["metrics"]})
    with (out / "results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["design", "variant", "model", "repeat", "runtime", "status", *metric_names]
        )
        for r in result.records:
            writer.writerow(
                [r["design"], r["variant"], r["model"], r["repeat"], r["runtime"], r["status"]]
                + ["" if r["metrics"].get(m) is None else r["metrics"][m] for m in metric_names]
            )
    (out / "manifest.json").write_text(
        json.dumps(_manifest(config), indent=2, ensure_ascii=False) + "\n"
    )
    if result.injection_records:
        with (out / "injection.jsonl").open("w", encoding="utf-8") as f:
            for r in result.injection_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _write_tables(result, config)
    _write_figures(result, config)
    (out / "report.md").write_text(_report(result, config), encoding="utf-8")


QUALITY_FIGURE = [
    "line_f1",
    "line_precision",
    "line_recall",
    "designator_f1",
    "acc_mpn",
    "acc_value",
    "mpn_coverage",
    "mpn_hallucination_rate",
]


def _estimate(data: list[float], seed: int) -> Estimate:
    values = [v for v in data if not math.isnan(v)]
    if not values:
        return Estimate(math.nan, math.nan, math.nan)
    lo, hi = bootstrap_ci(values, seed=seed)
    return Estimate(statistics.fmean(values), lo, hi)


def _injection_cells(result: ExperimentResult) -> dict[tuple[str, str], dict[str, list[float]]]:
    cells: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in result.injection_records:
        for metric in INJECTION_METRICS:
            cells[(r["variant"], r["model"])][metric].append(float(r[metric]))
    return cells


def _by_kind(result: ExperimentResult) -> dict[tuple[str, str, str], list[int]]:
    totals: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in result.injection_records:
        for kind, (injected, detected) in r["by_kind"].items():
            t = totals[(r["variant"], r["model"], kind)]
            t[0] += injected
            t[1] += detected
    return totals


def _write_tables(result: ExperimentResult, config: ExperimentConfig) -> None:
    """CSV tables for the thesis (imported into the DOCX, not retyped)."""
    tables = result.out_dir / "tables"
    tables.mkdir(exist_ok=True)
    injection = _injection_cells(result)
    with (tables / "variants.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "model", "metric", "better", "n", "mean", "ci_low", "ci_high"])
        for (variant, model), cell in sorted(result.cells.items()):
            sources = [(m, cell.metrics.get(m, []), d) for m, d in KEY_METRICS.items()] + [
                (m, injection[(variant, model)][m], d)
                for m, d in INJECTION_METRICS.items()
                if (variant, model) in injection
            ]
            for metric, data, direction in sources:
                est = _estimate(data, config.seed)
                n = sum(1 for v in data if not math.isnan(v))
                w.writerow(
                    [
                        variant,
                        model,
                        metric,
                        "higher" if direction > 0 else "lower",
                        n,
                        est.mean,
                        est.low,
                        est.high,
                    ]
                )
    with (tables / "paired.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "model",
                "metric",
                "better",
                "n",
                "mean_a",
                "mean_b",
                "diff",
                "ci_low",
                "ci_high",
                "p_value",
                "b_better",
                "a_better",
                "ties",
            ]
        )
        for model in config.models:
            comps = {
                **result.comparisons.get(model, {}),
                **result.injection_comparisons.get(model, {}),
            }
            for metric, c in comps.items():
                direction = {**KEY_METRICS, **INJECTION_METRICS}[metric]
                b_better, a_better = (c.wins_b, c.wins_a) if direction > 0 else (c.wins_a, c.wins_b)
                w.writerow(
                    [
                        model,
                        metric,
                        "higher" if direction > 0 else "lower",
                        c.n,
                        c.mean_a,
                        c.mean_b,
                        c.mean_diff,
                        c.ci_low,
                        c.ci_high,
                        c.p_value,
                        b_better,
                        a_better,
                        c.ties,
                    ]
                )
    with (tables / "detection_by_kind.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "model", "kind", "injected", "detected", "rate"])
        for (variant, model, kind), (injected, detected) in sorted(_by_kind(result).items()):
            w.writerow([variant, model, kind, injected, detected, detected / injected])


def _write_figures(result: ExperimentResult, config: ExperimentConfig) -> None:
    """SVG figures for chapter 7, one set per model."""
    figures = result.out_dir / "figures"
    figures.mkdir(exist_ok=True)
    injection = _injection_cells(result)
    kinds = _by_kind(result)

    def label(metric: str, direction: int) -> str:
        return metric if direction > 0 else f"{metric} (lower)"

    for model in config.models:
        cells = {v: c for (v, m), c in result.cells.items() if m == model}
        rows = [
            (
                label(metric, KEY_METRICS[metric]),
                {v: _estimate(c.metrics.get(metric, []), config.seed) for v, c in cells.items()},
            )
            for metric in QUALITY_FIGURE
        ]
        (figures / f"quality-{model}.svg").write_text(
            dot_interval_chart(f"BOM quality per variant - {model}", rows), encoding="utf-8"
        )
        designs = sorted({r["design"] for r in result.records if r["model"] == model})
        pairs = [
            (
                d,
                _design_mean(result.records, d, "A", model, "line_f1"),
                _design_mean(result.records, d, "B", model, "line_f1"),
            )
            for d in designs
        ]
        (figures / f"paired-line_f1-{model}.svg").write_text(
            slope_chart(f"Line F1, A vs B per design - {model}", "line_f1", pairs),
            encoding="utf-8",
        )

        def mean(variant: str, metric: str, cells: dict[str, Cell] = cells) -> float:
            cell = cells.get(variant)
            return _estimate(cell.metrics.get(metric, []) if cell else [], config.seed).mean

        panels = [
            ("LLM calls per run", {v: mean(v, "llm_calls") for v in cells}),
            (
                "tokens per run",
                {v: mean(v, "input_tokens") + mean(v, "output_tokens") for v in cells},
            ),
            ("cost per run [EUR]", {v: mean(v, "cost_eur") for v in cells}),
        ]
        (figures / f"cost-{model}.svg").write_text(
            bar_panels(f"Cost of a run per variant - {model}", panels), encoding="utf-8"
        )
        if any(m == model for (_, m) in injection):
            det_rows: list[tuple[str, dict[str, Estimate]]] = [
                (
                    label(metric, direction),
                    {
                        v: _estimate(data[metric], config.seed)
                        for (v, m), data in injection.items()
                        if m == model
                    },
                )
                for metric, direction in INJECTION_METRICS.items()
            ]
            for kind in sorted({k for (_, m, k) in kinds if m == model}):
                det_rows.append(
                    (
                        f"detected: {kind}",
                        {
                            v: Estimate(t[1] / t[0], math.nan, math.nan)
                            for (v, m, k), t in kinds.items()
                            if m == model and k == kind
                        },
                    )
                )
            (figures / f"detection-{model}.svg").write_text(
                dot_interval_chart(
                    f"Validation on injected errors - {model}",
                    det_rows,
                    note="Rates over trials (95 % bootstrap interval); per kind: share detected.",
                ),
                encoding="utf-8",
            )


def _report(result: ExperimentResult, config: ExperimentConfig) -> str:
    lines = [
        f"# Experiment `{config.name}`",
        "",
        "## Configuration",
        "",
        f"- designs: {', '.join(p.name for p in config.designs)}",
        f"- variants: {', '.join(config.variants)}; models: {', '.join(config.models)}; "
        f"repetitions: {config.repeats}; seed: {config.seed}",
        "- reproducibility: commit, prompt versions and rule pack in `manifest.json`",
        "",
        "## Results per variant",
        "",
        "Mean with 95 % bootstrap interval over runs.",
        "",
        "| variant | model | runs | " + " | ".join(KEY_METRICS) + " |",
        "|---|---|---|" + "---|" * len(KEY_METRICS),
    ]
    for (variant, model), cell in sorted(result.cells.items()):
        values = []
        for metric in KEY_METRICS:
            data = [v for v in cell.metrics.get(metric, []) if not math.isnan(v)]
            if not data:
                values.append(MISSING)
                continue
            lo, hi = bootstrap_ci(data, seed=config.seed)
            mean = statistics.fmean(data)
            values.append(
                _fmt(mean, metric)
                if lo == hi
                else f"{_fmt(mean, metric)} [{_fmt(lo, metric)}; {_fmt(hi, metric)}]"
            )
        lines.append(f"| {variant} | {model} | {cell.runs} | " + " | ".join(values) + " |")
    lines += ["", "## A vs B (paired)", ""]
    if not result.comparisons:
        lines.append("Both variants are needed for a paired comparison.")
    for model, comps in result.comparisons.items():
        lines += [
            f"### {model}",
            "",
            "Pairs are designs, each the mean over its repetitions (repetitions of one"
            " design are not independent). Difference B - A; p: two-sided exact paired"
            " permutation test - with n designs the smallest attainable p is 2 / 2^n.",
            "",
            "| metric | better | n | A | B | B - A [95 % CI] | p | B better / A better / ties |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for metric, c in comps.items():
            better = "higher" if KEY_METRICS[metric] > 0 else "lower"
            wins_b, wins_a = (
                (c.wins_b, c.wins_a) if KEY_METRICS[metric] > 0 else (c.wins_a, c.wins_b)
            )
            p = MISSING if math.isnan(c.p_value) else f"{c.p_value:.4f}"
            diff = (
                f"{_fmt(c.mean_diff, metric)} [{_fmt(c.ci_low, metric)}; {_fmt(c.ci_high, metric)}]"
            )
            lines.append(
                f"| {metric} | {better} | {c.n} | {_fmt(c.mean_a, metric)} | "
                f"{_fmt(c.mean_b, metric)} | {diff} | {p} | {wins_b} / {wins_a} / {c.ties} |"
            )
        lines.append("")
    if result.injection_records:
        lines += [
            "## Validation effectiveness (error injection)",
            "",
            f"{config.injection.errors} errors injected into each reference BOM, "
            f"{config.injection.trials} different mutations per design; A and B review the same"
            " faulty BOMs. Detected = a new finding on the affected line naming the field or a"
            " matching rule (variant-neutral); false alarm = a new finding matching no error.",
            "",
            "| variant | model | trials | injected | detected | detection rate [95 % CI] |"
            " false alarm rate |",
            "|---|---|---|---|---|---|---|",
        ]
        for (variant, model), inj in sorted(_injection_cells(result).items()):
            trials = [
                r
                for r in result.injection_records
                if (r["variant"], r["model"]) == (variant, model)
            ]
            det = _estimate(inj["detection_rate"], config.seed)
            fa = _estimate(inj["false_alarm_rate"], config.seed)
            lines.append(
                f"| {variant} | {model} | {len(trials)} | {sum(t['injected'] for t in trials)} | "
                f"{sum(t['detected'] for t in trials)} | {det.mean:.3f} "
                f"[{det.low:.3f}; {det.high:.3f}] | {fa.mean:.3f} |"
            )
        lines += [
            "",
            "| variant | model | error kind | injected | detected |",
            "|---|---|---|---|---|",
        ]
        for (variant, model, kind), (injected, detected) in sorted(_by_kind(result).items()):
            lines.append(f"| {variant} | {model} | {kind} | {injected} | {detected} |")
        for model, comps in result.injection_comparisons.items():
            lines += ["", f"Paired (designs), {model}:", ""]
            for metric, c in comps.items():
                p = MISSING if math.isnan(c.p_value) else f"{c.p_value:.4f}"
                lines.append(
                    f"- {metric}: A {c.mean_a:.3f}, B {c.mean_b:.3f}, B - A {c.mean_diff:.3f}"
                    f" [{c.ci_low:.3f}; {c.ci_high:.3f}], p {p}, n {c.n}"
                )
        lines.append("")
    lines += [
        "## Figures and tables",
        "",
        "`figures/*.svg` (quality with intervals, paired line F1 per design, cost, validation"
        " on injected errors) and `tables/*.csv` (per-variant estimates, paired tests,"
        " detection per error kind) are generated from the same records.",
        "",
        "## Repeatability",
        "",
        "Mean pairwise agreement of decisions (value, MPN per designator) between repetitions.",
        "",
        "| variant | model | agreement |",
        "|---|---|---|",
    ]
    for (variant, model), agreement in sorted(result.repeatability.items()):
        lines.append(f"| {variant} | {model} | {agreement:.3f} |")
    statuses = {f"{v}/{m}": dict(c.statuses) for (v, m), c in sorted(result.cells.items())}
    lines += ["", f"Run statuses: `{json.dumps(statuses)}`", ""]
    return "\n".join(lines)


@experiment_app.command("run")
def run_cmd(
    config_path: Annotated[Path, typer.Argument(exists=True, help="experiment YAML")],
    out: Annotated[Path, typer.Option(help="reports root")] = Path("evals/reports"),
) -> None:
    """Run the experiment matrix and write the report to <out>/<name>/."""
    from pydantic import ValidationError

    try:
        config = ExperimentConfig.from_file(config_path)
    except (ValidationError, yaml.YAMLError) as exc:
        typer.echo(f"error: invalid experiment configuration: {exc}", err=True)
        raise typer.Exit(2) from exc
    result = run_experiment(config, out)
    typer.echo(f"{len(result.records)} runs -> {result.out_dir / 'report.md'}", err=True)
