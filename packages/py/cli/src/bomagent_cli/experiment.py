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


def run_experiment(config: ExperimentConfig, out_root: Path) -> ExperimentResult:
    from bomagent_cli.main import collect_files

    out = out_root / config.name
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    boms: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for design_dir in config.designs:
        design = parse_files(collect_files([design_dir]))
        reference = load_reference(design_dir / "reference_bom.csv")
        design_mpns = {c.field("MPN") for c in design.components} - {""}
        for model in config.models:
            for variant in config.variants:
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
    result = ExperimentResult(out, records, dict(cells), comparisons, repeatability)
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
    (out / "report.md").write_text(_report(result, config), encoding="utf-8")


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
    lines += [
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
