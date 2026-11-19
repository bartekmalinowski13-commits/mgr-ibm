"""Thesis experiment (M8): variants {A, B} x models x designs x repetitions.

Every run is scored against the design's reference BOM with the same metrics as the
product (``bomagent_eval``). The output directory holds everything chapter 6/7 needs
and everything needed to reproduce it:

* ``runs.jsonl`` - one record per run (metrics, usage, status, design, variant, model),
  appended as each run finishes; ``injection.jsonl`` / ``injection_baselines.jsonl`` and
  ``boms/`` likewise - a crashed matrix resumes where it stopped and never pays twice for a
  finished run or trial;
* ``results.csv`` - the same, flat, for spreadsheets and plotting;
* ``report.md`` - configuration, per-variant results with 95 % bootstrap intervals,
  paired A-vs-B comparisons (permutation test), repeatability;
* ``manifest.json`` - written before the first run: configuration (incl. the run budget),
  commit and dirty flag, prompt versions (``version+sha8``), rule pack, model catalogue
  entries, seeds; restarts are appended under ``resumed``.

Pairing: per model, variant A and B are compared per design, each design contributing
the mean over its repetitions (repetitions measure stability; they are not independent
samples - no pseudoreplication). Only the fake provider runs without credentials; real
models go through the LLM gateway configured in the environment and must be enabled in
the catalogue.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import typer
import yaml
from pydantic import BaseModel, Field, field_validator

from bomagent_bom.model import BomVersion, Finding, Severity, Usage
from bomagent_cad import parse_files
from bomagent_cli import thesis_assets
from bomagent_cli.experiment_figures import Estimate, bar_panels, dot_interval_chart, slope_chart
from bomagent_eval.experiment_stats import (
    PairedComparison,
    bootstrap_ci,
    cluster_bootstrap_ci,
    compare_paired,
    holm_adjust,
)
from bomagent_eval.injection import rule_coverage
from bomagent_eval.metrics import evaluate
from bomagent_eval.reference import load_reference
from bomagent_eval.stats import pairwise_agreement

if TYPE_CHECKING:
    from bomagent_agents.contracts import RunConfig
    from bomagent_llm.catalog import ModelSpec

MISSING = "n/a"
experiment_app = typer.Typer(help="Thesis experiment: variant A vs B on the evaluation set.")
thesis_assets.register(experiment_app)

SAMPLING_NOTE = (
    "temperature is fixed by the platform and the seed only drives the experiment's own "
    "sampling (mutations, bootstrap); hosted models are not deterministic even at "
    "temperature 0, so repeats measure run-to-run variance"
)
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
    #: primary PB2 metric: rejected MPN decisions / all agent MPN decisions (TH-01)
    "attempted_mpn_hallucination_rate": -1,
    #: residual: unverified MPNs left in the final BOM (the guard makes it ~0 for every variant)
    "mpn_hallucination_rate": -1,
    "llm_calls": -1,
    "input_tokens": -1,
    "output_tokens": -1,
    "cost_eur": -1,
    "wall_time_s": -1,
}


Variant = Literal["A", "B"]
#: validation metrics on injected errors; direction as in KEY_METRICS
#: pre-registered primary family (docs/thesis/PREREJESTRACJA.md): Holm-adjusted together;
#: everything else is secondary and reported without multiplicity correction
PRIMARY_METRICS = ("line_f1", "attempted_mpn_hallucination_rate", "cost_eur")
INJECTION_METRICS: dict[str, int] = {"detection_rate": 1, "false_alarm_rate": -1}


class InjectionConfig(BaseModel):
    """Validation effectiveness: known errors injected into each reference BOM."""

    errors: int = Field(default=5, ge=1, le=20)
    #: different mutations per design (0 switches the measurement off)
    trials: int = Field(default=3, ge=0, le=50)
    #: error kinds to inject (default: the rule-covered mix); add the beyond-rule kinds
    #: (``bomagent_eval.injection.BEYOND_RULES_KINDS``) to test what rules cannot see
    kinds: list[str] | None = None

    @field_validator("kinds")
    @classmethod
    def _known_kinds(cls, v: list[str] | None) -> list[str] | None:
        from bomagent_eval.injection import ERROR_KINDS

        unknown = sorted(set(v or []) - set(ERROR_KINDS))
        if unknown or v == []:
            raise ValueError(f"unknown or empty injection kinds: {unknown or v}")
        return v


class RunBudget(BaseModel):
    """Limits of every run and every validate call (``RunConfig``): part of the
    pre-registered matrix and recorded in ``manifest.json``. The worker's production default
    (``RunConfig``) is separate."""

    max_llm_calls: int = Field(default=200, ge=1)
    max_total_tokens: int = Field(default=2_000_000, ge=1)
    #: wall clock after which no new model call starts; must cover one call of every
    #: sequential step at its per-call budget (``minimum_run_timeout_s``), else a slow
    #: provider day, not the architecture, decides how far a run gets
    timeout_s: float = Field(default=3600.0, gt=0)
    concurrency: int = Field(default=8, ge=1, le=64)
    kb_k: int = Field(default=5, ge=1, le=20)
    max_repair_iterations: int = Field(default=2, ge=0, le=5)


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
    budget: RunBudget = Field(default_factory=RunBudget)

    @classmethod
    def from_file(cls, path: Path) -> ExperimentConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


#: answer budgets (``max_tokens``) of the calls on each variant's sequential critical path:
#: A - extract_group, one mpn_select wave, validate, compose (``variant_a.py``);
#: B - one mpn_select wave, two repair iterations (``variant_b.py``, default 4096)
CRITICAL_PATH_MAX_TOKENS: dict[str, tuple[int, ...]] = {
    "A": (16_000, 1_024, 8_000, 16_000),
    "B": (1_024, 4_096, 4_096),
}


def minimum_run_timeout_s(spec: ModelSpec) -> float:
    """Smallest run wall clock that lets one call of every sequential step use its full
    per-call budget (``call_timeout_s``, incl. the model's reasoning tokens)."""
    from bomagent_llm.chat import call_timeout_s

    return max(
        sum(call_timeout_s(t + spec.reasoning_tokens) for t in path)
        for path in CRITICAL_PATH_MAX_TOKENS.values()
    )


def _run_config(config: ExperimentConfig, variant: Variant, model: str) -> RunConfig:
    from bomagent_agents.contracts import RunConfig

    return RunConfig(variant=variant, model_id=model, **config.budget.model_dump())


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


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed git subcommands, no shell
            ["git", *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _commit() -> str:
    out = _git("rev-parse", "HEAD")
    return out.strip() if out is not None else "unknown"


def _dirty() -> bool | None:
    """Uncommitted changes in the checkout (None when git is unavailable)."""
    out = _git("status", "--porcelain")
    return None if out is None else bool(out.strip())


def kb_snapshot(directory: Path) -> tuple[str, int]:
    """Content hash and file count of the datasheets an in-memory run retrieves from.

    Mirrors ``InMemoryRetriever.from_directory`` (same file filter), so two runs with the same
    snapshot id saw exactly the same knowledge base."""
    digest = hashlib.sha256()
    count = 0
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".md", ".txt", ".pdf"}:
            continue
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
        count += 1
    return f"sha256:{digest.hexdigest()}", count


def _manifest(config: ExperimentConfig) -> dict[str, Any]:
    """Written before the first run (the state the matrix starts from)."""
    from bomagent_agents.prompts import load_prompt
    from bomagent_llm.catalog import load_catalog
    from bomagent_llm.chat import DEFAULT_TEMPERATURE
    from bomagent_rules.core_v1 import PACK_VERSION

    catalog = load_catalog()
    snapshot_id, kb_files = kb_snapshot(config.kb_dir)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "commit": _commit(),
        "dirty": _dirty(),
        "config": json.loads(config.model_dump_json()),
        "budget": config.budget.model_dump(),
        "minimum_run_timeout_s": {m: minimum_run_timeout_s(catalog.get(m)) for m in config.models},
        "prompts": {p: load_prompt(p).full_version for p in PROMPT_IDS},
        "rule_pack": {"id": "core", "version": PACK_VERSION},
        "models": {m: catalog.get(m).model_dump(mode="json") for m in config.models},
        "retrieval": {
            "retriever": "in-memory",
            "embedding": "hashing (feature hashing, non-semantic)",
            "reranker": "lexical",
            "kb_dir": str(config.kb_dir),
            "kb_snapshot_id": snapshot_id,
            "kb_files": kb_files,
        },
        "model_ids": {m: catalog.get(m).gateway_model for m in config.models},
        "sampling": {
            "temperature": DEFAULT_TEMPERATURE,
            "seed": config.seed,
            "note": SAMPLING_NOTE,
        },
        "resumed": [],
    }


class _Store:
    """Append-only, crash-safe result files of one matrix (I5).

    Every finished run, validation baseline and injection trial is appended (and fsynced) as
    soon as it is paid for; a restart loads them and skips what is done, so no model call
    is repeated for a finished cell. A line cut off by a crash is dropped on load."""

    RUNS = "runs.jsonl"
    TRIALS = "injection.jsonl"
    BASELINES = "injection_baselines.jsonl"

    def __init__(self, out: Path) -> None:
        self.out = out
        self.runs = self._load(self.RUNS)
        self.trials = self._load(self.TRIALS)
        self.baselines = {
            (b["design_dir"], b["variant"], b["model"]): b for b in self._load(self.BASELINES)
        }
        (out / "boms").mkdir(exist_ok=True)

    def _load(self, name: str) -> list[dict[str, Any]]:
        path = self.out / name
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        records = []
        for n, line in enumerate(lines):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if n != len(lines) - 1:
                    raise ValueError(f"{path}: corrupt line {n + 1}") from None
                # the write the crash interrupted: drop it, the record is redone
                path.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")
        return records

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with (self.out / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def add_run(self, record: dict[str, Any], bom: BomVersion | None) -> None:
        if bom is not None:  # the BOM first: a recorded run always has its BOM
            (self.out / "boms" / f"{_bom_name(record)}.json").write_text(
                bom.model_dump_json(), encoding="utf-8"
            )
        self._append(self.RUNS, record)
        self.runs.append(record)

    def add_trial(self, record: dict[str, Any]) -> None:
        self._append(self.TRIALS, record)
        self.trials.append(record)

    def add_baseline(self, record: dict[str, Any]) -> None:
        self._append(self.BASELINES, record)
        self.baselines[(record["design_dir"], record["variant"], record["model"])] = record

    def bom(self, record: dict[str, Any]) -> BomVersion | None:
        path = self.out / "boms" / f"{_bom_name(record)}.json"
        if not path.exists():
            return None
        return BomVersion.model_validate_json(path.read_text(encoding="utf-8"))


def _bom_name(record: dict[str, Any]) -> str:
    raw = f"{record['design']}--{record['variant']}--{record['model']}--{record['repeat']}"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def _billing(findings: list[Any]) -> dict[str, int]:
    """Failed calls whose cost is an estimate (timeouts) or an explicit 0 (I3)."""
    from bomagent_agents.runtime_base import BILLING_FLAGS

    return {
        f"{kind}_calls": sum(1 for f in findings if f.rule_id == rule)
        for kind, rule in BILLING_FLAGS.items()
    }


async def _run_one(
    design: Any, variant: Variant, model: str, config: ExperimentConfig, spent: dict[str, Any]
) -> tuple[Any, set[str]]:
    """One run; ``spent["usage"]`` follows the spend step by step, so a run that raises
    still reports what it cost."""
    from bomagent_agents.contracts import RunInput
    from bomagent_agents.registry import context_factory, runtime_for
    from bomagent_agents.retrieval import InMemoryRetriever
    from bomagent_bom.model import Requirements
    from bomagent_cli.main import build_chat

    async def on_step(_step: Any, usage: Any) -> None:
        spent["usage"] = usage

    retriever = await InMemoryRetriever.from_directory(config.kb_dir)
    chat = build_chat(model, config.cassettes)
    runtime = runtime_for(
        variant,
        context_factory(chat, retriever, on_step=on_step),
        runtime=config.runtimes.get(variant),
    )
    result = await runtime.run(
        RunInput(
            design=design,
            requirements=Requirements(),
            config=_run_config(config, variant, model),
        )
    )
    return result, await retriever.known_mpns()


async def _validate(
    variant: Variant, model: str, config: ExperimentConfig, items: list[Any]
) -> tuple[str, list[Any]]:
    """One validator call with its own budget (a fresh context per call, I1): status and
    findings. Any status but ``completed`` means the validator did not deliver a review."""
    from bomagent_agents.retrieval import InMemoryRetriever
    from bomagent_agents.validation import validate_bom, validation_context
    from bomagent_bom.model import Requirements
    from bomagent_cli.main import build_chat

    retriever = await InMemoryRetriever.from_directory(config.kb_dir)
    ctx = validation_context(
        build_chat(model, config.cassettes),
        retriever,
        _run_config(config, variant, model),
        Requirements(),
    )
    findings = await validate_bom(variant, ctx, items)
    return ctx.status, findings


def _inject_cell(
    design_dir: str,
    design: str,
    reference: list[Any],
    variant: Variant,
    model: str,
    config: ExperimentConfig,
    store: _Store,
) -> None:
    """Validator of ``variant`` on ``trials`` mutated copies of the reference BOM.

    The mutation of trial ``t`` depends only on the seed and ``t``, so A and B review
    exactly the same faulty BOMs (paired). New findings are counted against the
    validator's own findings on the clean reference (baseline). A validator call that does
    not complete (model failure, budget stop, exception) is recorded with its status and
    no rates - not as a miss; a failed baseline voids the cell (same rule for A and B)."""
    from bomagent_bom.model import Finding
    from bomagent_eval.injection import detection_report, inject_errors

    cell = (design_dir, variant, model)
    done = {t["trial"] for t in store.trials if (t["design_dir"], t["variant"], t["model"]) == cell}
    if len(done) >= config.injection.trials:
        return
    baseline = store.baselines.get(cell)
    if baseline is None:
        status, error, findings = _guarded_validate(variant, model, config, reference)
        baseline = {
            "design_dir": design_dir,
            "design": design,
            "variant": variant,
            "model": model,
            "status": status,
            "error": error,
            "findings": [f.model_dump(mode="json") for f in findings],
        }
        store.add_baseline(baseline)
    clean = [Finding.model_validate(f) for f in baseline["findings"]]
    for trial in range(config.injection.trials):
        if trial in done:
            continue
        mutated, errors = inject_errors(
            reference,
            n=config.injection.errors,
            seed=config.seed * 1009 + trial,
            kinds=tuple(config.injection.kinds) if config.injection.kinds else None,
        )
        if not errors:
            continue
        record: dict[str, Any] = {
            "design_dir": design_dir,
            "design": design,
            "variant": variant,
            "model": model,
            "trial": trial,
            "errors": [{"kind": e.kind, "line": e.line, "refdes": e.refdes} for e in errors],
            "injected": None,
            "detected": None,
            "new_findings": None,
            "false_alarms": None,
            "detection_rate": None,
            "false_alarm_rate": None,
            "by_kind": {},
            "false_alarms_by_rule": {},
        }
        if baseline["status"] != "completed":
            store.add_trial(record | {"status": "baseline_failed", "error": baseline["error"]})
            continue
        status, error, findings = _guarded_validate(variant, model, config, mutated)
        if status == "completed":
            report = detection_report(errors, findings, clean)
            record |= {
                "injected": report.injected,
                "detected": report.detected,
                "new_findings": report.new_findings,
                "false_alarms": report.false_alarms,
                "detection_rate": _num(report.detection_rate),
                "false_alarm_rate": _num(report.false_alarm_rate),
                "by_kind": {k: list(v) for k, v in report.by_kind.items()},
                "false_alarms_by_rule": report.false_alarms_by_rule,
            }
        store.add_trial(record | {"status": status, "error": error})


def _guarded_validate(
    variant: Variant, model: str, config: ExperimentConfig, items: list[Any]
) -> tuple[str, str | None, list[Any]]:
    from bomagent_llm.chat import CassetteMissError

    try:
        status, findings = asyncio.run(_validate(variant, model, config, items))
    except CassetteMissError:
        raise  # an incomplete replay is a setup error: stop, fix, resume
    except Exception as exc:  # any other failure is a recorded outcome, not a lost matrix
        return "error", type(exc).__name__, []
    return status, None, findings


def _num(v: float) -> float | None:
    return None if math.isnan(v) else v


#: manifest parts that define the experiment: a restart must find them unchanged
RESUME_INVARIANTS: tuple[tuple[str, ...], ...] = (
    ("config",),
    ("budget",),
    ("prompts",),
    ("rule_pack",),
    ("retrieval", "kb_snapshot_id"),
    ("model_ids",),
    ("models",),
)


def _part(manifest: dict[str, Any], keys: tuple[str, ...]) -> Any:
    value: Any = manifest
    for k in keys:
        value = value.get(k) if isinstance(value, dict) else None
    return value


def _open_matrix(
    config: ExperimentConfig, out: Path, *, allow_code_drift: bool = False
) -> dict[str, Any]:
    """Write the manifest before the first run, or check that a restart continues the same
    experiment and note the restart in the manifest. Returns the code provenance of this
    session (``commit``, ``dirty``), stored with every record it produces.

    A restart is refused when the configuration, budget, prompt versions, rule pack, KB
    snapshot or model entries differ from the manifest, and when the code commit differs
    unless ``allow_code_drift`` (then the drift is recorded)."""
    path = out / "manifest.json"
    now = _manifest(config)
    session = {"commit": now["commit"], "dirty": now["dirty"]}
    if not path.exists():
        path.write_text(json.dumps(now, indent=2, ensure_ascii=False) + "\n")
        return session
    manifest = json.loads(path.read_text(encoding="utf-8"))
    changed = [
        ".".join(keys) for keys in RESUME_INVARIANTS if _part(manifest, keys) != _part(now, keys)
    ]
    if changed:
        raise ValueError(
            f"{out} holds a matrix with a different configuration ({', '.join(changed)} "
            "changed); use another name or directory"
        )
    drift = manifest.get("commit") != now["commit"]
    if drift and not allow_code_drift:
        raise ValueError(
            f"{out} was started at commit {manifest.get('commit')}, the code is now at "
            f"{now['commit']}; resume with --allow-code-drift to continue (recorded) or "
            "start a new matrix"
        )
    manifest.setdefault("resumed", []).append(
        {"at": datetime.now(UTC).isoformat(), **session, "code_drift": drift}
    )
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return session


def run_experiment(
    config: ExperimentConfig, out_root: Path, *, allow_code_drift: bool = False
) -> ExperimentResult:
    """Run (or resume) the matrix. Results are persisted as each run finishes; starting
    again with the same configuration and directory skips what is already done."""
    from bomagent_agents.registry import design_mpns as read_design_mpns
    from bomagent_cli.main import collect_files
    from bomagent_llm.catalog import load_catalog
    from bomagent_llm.chat import CassetteMissError

    catalog = load_catalog()
    for model in config.models:
        floor = minimum_run_timeout_s(catalog.get(model))
        if config.budget.timeout_s < floor:
            raise ValueError(
                f"budget.timeout_s {config.budget.timeout_s:g} s is shorter than the per-call "
                f"budgets of one run on {model} ({floor:g} s)"
            )
    designs = []
    seen: dict[str, Path] = {}
    for design_dir in config.designs:
        design = parse_files(collect_files([design_dir]))
        if design.design_name in seen:
            raise ValueError(
                f"{design_dir} and {seen[design.design_name]} parse to the same design name "
                f"{design.design_name!r} (one statistical unit each)"
            )
        seen[design.design_name] = design_dir
        designs.append((design_dir, design, load_reference(design_dir / "reference_bom.csv")))

    out = out_root / config.name
    out.mkdir(parents=True, exist_ok=True)
    session = _open_matrix(config, out, allow_code_drift=allow_code_drift)
    store = _Store(out)
    done = {(r["design_dir"], r["variant"], r["model"], r["repeat"]) for r in store.runs}
    for design_dir, design, reference in designs:
        key = str(design_dir)
        mpns = read_design_mpns(design)
        for model in config.models:
            for variant in config.variants:
                if config.injection.trials:
                    _inject_cell(key, design.design_name, reference, variant, model, config, store)
                for rep in range(config.repeats):
                    if (key, variant, model, rep) in done:
                        continue
                    record: dict[str, Any] = {
                        "design_dir": key,
                        "design": design.design_name,
                        "variant": variant,
                        "model": model,
                        "repeat": rep,
                        **session,
                    }
                    spent: dict[str, Any] = {}
                    try:
                        result, known = asyncio.run(_run_one(design, variant, model, config, spent))
                    except CassetteMissError:
                        raise  # an incomplete replay is a setup error: stop, fix, resume
                    except Exception as exc:  # recorded and reported (PREREJESTRACJA 7.1)
                        # scored like a failed run: an empty BOM with the spend so far, so the
                        # design stays in the paired comparison (no survivor bias)
                        usage = spent.get("usage") or Usage()
                        bom = _error_bom(design.design_name, variant, exc, usage)
                        store.add_run(
                            record
                            | {
                                "runtime": config.runtimes.get(variant)
                                or ("langgraph_a" if variant == "A" else "langgraph_b"),
                                "status": "error",
                                "error": type(exc).__name__,
                                "metrics": _score(bom, reference, None, mpns, variant, model),
                                "billing": {"estimated_calls": 0, "unbilled_calls": 0},
                                "spent": usage.model_dump(mode="json"),
                            },
                            bom,
                        )
                        continue
                    store.add_run(
                        record
                        | {
                            "runtime": result.runtime,
                            "status": result.status,
                            "metrics": _score(result.bom, reference, known, mpns, variant, model),
                            "billing": _billing(result.bom.findings),
                        },
                        result.bom,
                    )
    return _analyse(config, out, store)


def _error_bom(design: str, variant: str, exc: Exception, usage: Usage) -> BomVersion:
    """What a run that raised delivered: no lines, its spend and the reason (type only)."""
    finding = Finding(
        rule_id="run.error",
        severity=Severity.ERROR,
        message=f"run raised {type(exc).__name__}",
    )
    return BomVersion(
        design_name=design, variant=variant, items=[], findings=[finding], usage=usage
    )


def _score(
    bom: BomVersion,
    reference: list[Any],
    known: set[str] | None,
    mpns: set[str],
    variant: str,
    model: str,
) -> dict[str, float | None]:
    report = evaluate(
        bom,
        reference,
        known_mpns=known,
        design_mpns=mpns,
        design=bom.design_name,
        variant=variant,
        model=model,
    )
    return {k: _num(v) for k, v in report.summary().items()}


def _analyse(config: ExperimentConfig, out: Path, store: _Store) -> ExperimentResult:
    wanted = {str(d) for d in config.designs}
    records = [r for r in store.runs if r["design_dir"] in wanted]
    injection_records = [t for t in store.trials if t["design_dir"] in wanted]
    boms: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for r in records:
        bom = store.bom(r)
        if bom is not None:
            boms[(r["design"], r["variant"], r["model"])].append(bom)

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
                comparisons[model][metric] = _with_cluster_ci(
                    compare_paired(a, b, seed=config.seed), records, designs, model, metric, config
                )
            # the registered family has a fixed size (M1): an undefined p keeps its slot
            adjusted = holm_adjust(
                {m: comparisons[model][m].p_value for m in PRIMARY_METRICS},
                family_size=len(PRIMARY_METRICS),
            )
            for metric, p_holm in adjusted.items():
                comparisons[model][metric] = comparisons[model][metric].model_copy(
                    update={"p_holm": p_holm}
                )

    repeatability = {
        (v, m): statistics.fmean(
            pairwise_agreement(runs) for (d, v2, m2), runs in boms.items() if (v2, m2) == (v, m)
        )
        for (v, m) in cells
        if any((v2, m2) == (v, m) for (_, v2, m2) in boms)
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


def _with_cluster_ci(
    comparison: PairedComparison,
    records: list[dict[str, Any]],
    designs: list[str],
    model: str,
    metric: str,
    config: ExperimentConfig,
) -> PairedComparison:
    """Sensitivity analysis: cluster bootstrap of the B - A difference (designs = clusters,
    repetition i of A paired with repetition i of B)."""

    def runs(design: str, variant: str) -> dict[int, float]:
        return {
            r["repeat"]: float(r["metrics"][metric])
            for r in records
            if (r["design"], r["variant"], r["model"]) == (design, variant, model)
            and r["metrics"].get(metric) is not None
        }

    clusters = []
    for design in designs:
        a, b = runs(design, "A"), runs(design, "B")
        clusters.append([b[i] - a[i] for i in sorted(a.keys() & b.keys())])
    lo, hi = cluster_bootstrap_ci(clusters, seed=config.seed)
    return comparison.model_copy(update={"cluster_ci_low": lo, "cluster_ci_high": hi})


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
    """Mean over the design's scored trials; failed trials (no review) are not misses."""
    values = [
        float(r[metric])
        for r in records
        if (r["design"], r["variant"], r["model"]) == (design, variant, model)
        and r.get(metric) is not None
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
    """Derived files; ``runs.jsonl``, ``injection.jsonl`` and ``manifest.json`` are written
    as the matrix runs (``_Store``, ``_open_matrix``)."""
    out = result.out_dir
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
    "attempted_mpn_hallucination_rate",
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
            if r.get(metric) is not None:  # failed trials and undefined rates are left out
                cells[(r["variant"], r["model"])][metric].append(float(r[metric]))
    return cells


def _false_alarms_by_rule(result: ExperimentResult) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in result.injection_records:
        for rule, n in r.get("false_alarms_by_rule", {}).items():
            out[(r["variant"], r["model"], rule)] += n
    return dict(out)


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
                "primary",
                "p_holm",
                "effect_size",
                "cluster_ci_low",
                "cluster_ci_high",
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
                        metric in PRIMARY_METRICS,
                        c.p_holm,
                        c.effect_size,
                        c.cluster_ci_low,
                        c.cluster_ci_high,
                        b_better,
                        a_better,
                        c.ties,
                    ]
                )
    with (tables / "detection_by_kind.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "model", "kind", "rule_covered", "injected", "detected", "rate"])
        coverage = rule_coverage()
        for (variant, model, kind), (injected, detected) in sorted(_by_kind(result).items()):
            w.writerow(
                [
                    variant,
                    model,
                    kind,
                    coverage.get(kind, False),
                    injected,
                    detected,
                    detected / injected,
                ]
            )


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
        "Mean with 95 % bootstrap interval over runs - descriptive only: repetitions of one"
        " design are not independent; the inferential intervals are the paired ones below.",
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
            "Primary family (Holm-adjusted together, see `docs/thesis/PREREJESTRACJA.md`):"
            f" {', '.join(f'`{m}`' for m in PRIMARY_METRICS)}; other rows are secondary and"
            " carry no multiplicity correction. d_z = mean(B - A) / sd(B - A), the standardised"
            " paired effect size. Cluster CI: sensitivity analysis resampling designs and then"
            " repetitions (not a replacement for the permutation test).",
            "",
            "| metric | better | pairs (dropped) | A | B | B - A [95 % CI] | d_z | p |"
            " p (Holm) | cluster CI | B better / A better / ties |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for metric, c in comps.items():
            better = "higher" if KEY_METRICS[metric] > 0 else "lower"
            wins_b, wins_a = (
                (c.wins_b, c.wins_a) if KEY_METRICS[metric] > 0 else (c.wins_a, c.wins_b)
            )
            p = MISSING if math.isnan(c.p_value) else f"{c.p_value:.4f}"
            holm = MISSING if math.isnan(c.p_holm) else f"{c.p_holm:.4f}"
            dz = MISSING if math.isnan(c.effect_size) else f"{c.effect_size:.2f}"
            cluster = (
                MISSING
                if math.isnan(c.cluster_ci_low)
                else f"[{_fmt(c.cluster_ci_low, metric)}; {_fmt(c.cluster_ci_high, metric)}]"
            )
            diff = (
                f"{_fmt(c.mean_diff, metric)} [{_fmt(c.ci_low, metric)}; {_fmt(c.ci_high, metric)}]"
            )
            dropped = _dropped_pairs(result.records, model, metric)
            lines.append(
                f"| {metric} | {better} | {c.n} ({len(dropped)}) | {_fmt(c.mean_a, metric)} | "
                f"{_fmt(c.mean_b, metric)} | {diff} | {dz} | {p} | {holm} | {cluster} | "
                f"{wins_b} / {wins_a} / {c.ties} |"
            )
        dropped_rows = [
            f"- `{metric}`: {', '.join(f'{d} ({why})' for d, why in dropped)}"
            for metric in comps
            if (dropped := _dropped_pairs(result.records, model, metric))
        ]
        if dropped_rows:
            lines += [
                "",
                "Dropped pairs (the metric is undefined for a variant on that design - e.g. no"
                " agent MPN decision - or the variant has no run):",
                "",
                *dropped_rows,
            ]
        lines.append("")
    if result.injection_records:
        lines += _injection_lines(result, config)
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
    lines += _accounting_lines(result)
    lines += _provenance_lines(result)
    return "\n".join(lines)


def _dropped_pairs(records: list[dict[str, Any]], model: str, metric: str) -> list[tuple[str, str]]:
    """Designs left out of the paired comparison of ``metric``, with the variant(s) whose
    design mean is undefined."""
    designs = sorted({r["design"] for r in records if r["model"] == model})
    out = []
    for design in designs:
        missing = [
            v for v in ("A", "B") if math.isnan(_design_mean(records, design, v, model, metric))
        ]
        if missing:
            out.append((design, "undefined for " + " and ".join(missing)))
    return out


def _provenance_lines(result: ExperimentResult) -> list[str]:
    """Code the runs were produced with: one row per (commit, dirty), from the manifest
    and the records (a resumed matrix may span commits, ``--allow-code-drift``)."""
    path = result.out_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sessions = [
        (
            "start",
            manifest.get("created_at", MISSING),
            manifest.get("commit"),
            manifest.get("dirty"),
        )
    ] + [
        (
            "resume" + (" (code drift)" if r.get("code_drift") else ""),
            r["at"],
            r["commit"],
            r["dirty"],
        )
        for r in manifest.get("resumed", [])
    ]
    runs: dict[tuple[Any, Any], int] = defaultdict(int)
    for r in result.records:
        runs[(r.get("commit"), r.get("dirty"))] += 1
    lines = [
        "## Code provenance",
        "",
        "| session | at | commit | dirty | runs recorded with it |",
        "|---|---|---|---|---|",
    ]
    for kind, at, commit, dirty in sessions:
        lines.append(f"| {kind} | {at} | `{commit}` | {dirty} | {runs.pop((commit, dirty), 0)} |")
    for (commit, dirty), n in sorted(runs.items(), key=str):  # records without a session row
        lines.append(f"| (records) | {MISSING} | `{commit}` | {dirty} | {n} |")
    lines.append("")
    return lines


def _injection_lines(result: ExperimentResult, config: ExperimentConfig) -> list[str]:
    """Report section on validation effectiveness (error injection)."""
    lines = [
        "## Validation effectiveness (error injection)",
        "",
        f"{config.injection.errors} errors injected into each reference BOM, "
        f"{config.injection.trials} different mutations per design; A and B review the same"
        " faulty BOMs. Detected = a new finding on the affected line naming the field or a"
        " matching rule (variant-neutral); false alarm = a new finding matching no error.",
        "",
        "A validator call that did not complete (model failure, budget stop, error) is a"
        " failed trial, not a miss: it has no rates and is counted separately; a failed"
        " baseline voids the design's trials (`baseline_failed`). False alarm rate: share"
        " of new findings matching no error (undefined without new findings).",
        "",
        "| variant | model | trials | failed trials | injected | detected |"
        " detection rate [95 % CI] | false alarm rate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    injection = _injection_cells(result)
    pairs = sorted({(r["variant"], r["model"]) for r in result.injection_records})
    for variant, model in pairs:
        trials = [
            r for r in result.injection_records if (r["variant"], r["model"]) == (variant, model)
        ]
        scored = [t for t in trials if t["status"] == "completed"]
        det = _estimate(injection[(variant, model)]["detection_rate"], config.seed)
        fa = _estimate(injection[(variant, model)]["false_alarm_rate"], config.seed)
        lines.append(
            f"| {variant} | {model} | {len(trials)} | {len(trials) - len(scored)} | "
            f"{sum(t['injected'] for t in scored)} | {sum(t['detected'] for t in scored)} | "
            f"{_fmt(det.mean, 'rate')} [{_fmt(det.low, 'rate')}; {_fmt(det.high, 'rate')}] | "
            f"{_fmt(fa.mean, 'rate')} |"
        )
    trial_statuses: dict[str, int] = defaultdict(int)
    for t in result.injection_records:
        trial_statuses[f"{t['variant']}/{t['model']}/{t['status']}"] += 1
    lines += ["", f"Trial statuses: `{json.dumps(dict(sorted(trial_statuses.items())))}`"]
    lines += [
        "",
        "| variant | model | error kind | rule coverage | injected | detected |",
        "|---|---|---|---|---|---|",
    ]
    coverage = rule_coverage()
    for (variant, model, kind), (injected, detected) in sorted(_by_kind(result).items()):
        covered = "yes" if coverage.get(kind) else "no"
        lines.append(f"| {variant} | {model} | {kind} | {covered} | {injected} | {detected} |")
    stray = _false_alarms_by_rule(result)
    if stray:
        lines += ["", "False alarms per rule (findings matching no injected error):", ""]
        lines += [f"- {v} / {m} / `{rule}`: {n}" for (v, m, rule), n in sorted(stray.items())]
    for model, comps in result.injection_comparisons.items():
        lines += ["", f"Paired (designs), {model}:", ""]
        for metric, c in comps.items():
            p = MISSING if math.isnan(c.p_value) else f"{c.p_value:.4f}"
            lines.append(
                f"- {metric}: A {c.mean_a:.3f}, B {c.mean_b:.3f}, B - A {c.mean_diff:.3f}"
                f" [{c.ci_low:.3f}; {c.ci_high:.3f}], p {p}, n {c.n}"
            )
    lines.append("")
    return lines


def _accounting_lines(result: ExperimentResult) -> list[str]:
    """Calls whose cost is not provider-metered, and spend of runs that ended in an error
    (their cost is not in the metric tables)."""
    lines = [
        "## Cost accounting",
        "",
        "Calls with estimated usage: timed out at the gateway, billed by the provider but"
        " without a usage report - priced from the prompt size, a lower bound. Unbilled calls:"
        " rejected or undelivered, recorded as 0. Error runs: exception inside the run; their"
        " spend up to the failure is below and not in the per-variant tables.",
        "",
        "| variant | model | runs | calls with estimated usage | unbilled calls | error runs |"
        " spend of error runs [EUR] |",
        "|---|---|---|---|---|---|---|",
    ]
    for variant, model in sorted({(r["variant"], r["model"]) for r in result.records}):
        runs = [r for r in result.records if (r["variant"], r["model"]) == (variant, model)]
        billing = [r.get("billing", {}) for r in runs]
        errors = [r for r in runs if r["status"] == "error"]
        lines.append(
            f"| {variant} | {model} | {len(runs)} | "
            f"{sum(b.get('estimated_calls', 0) for b in billing)} | "
            f"{sum(b.get('unbilled_calls', 0) for b in billing)} | {len(errors)} | "
            f"{sum(float(r.get('spent', {}).get('cost_eur', 0.0)) for r in errors):.4f} |"
        )
    lines.append("")
    return lines


@experiment_app.command("run")
def run_cmd(
    config_path: Annotated[Path, typer.Argument(exists=True, help="experiment YAML")],
    out: Annotated[Path, typer.Option(help="reports root")] = Path("evals/reports"),
    allow_code_drift: Annotated[
        bool,
        typer.Option(
            "--allow-code-drift",
            help="resume a matrix started at another commit (recorded in manifest and report)",
        ),
    ] = False,
) -> None:
    """Run the experiment matrix and write the report to <out>/<name>/.

    Results are saved as each run finishes; after a crash, run the same command again: the
    finished runs and trials are kept and not paid for again."""
    from pydantic import ValidationError

    from bomagent_llm.chat import CassetteMissError

    try:
        config = ExperimentConfig.from_file(config_path)
    except (ValidationError, yaml.YAMLError) as exc:
        typer.echo(f"error: invalid experiment configuration: {exc}", err=True)
        raise typer.Exit(2) from exc
    try:
        result = run_experiment(config, out, allow_code_drift=allow_code_drift)
    except (ValueError, CassetteMissError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"{len(result.records)} runs -> {result.out_dir / 'report.md'}", err=True)
