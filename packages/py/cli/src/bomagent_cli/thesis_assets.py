"""Thesis appendices and experiment status page generated from a run directory (TH-08/TH-09).

``bomagent experiment appendices RUN_DIR`` writes (Polish headings, content from the repo):

* ``dodatek-a-prompty.md`` - every prompt of the run with version, sha256 and full text;
* ``dodatek-b-schemat-bom.json`` - JSON Schema of the BOM;
* ``dodatek-c-uruchomienie.md`` - how to reproduce the run (commit, configuration, commands);
* ``tabela-pb-metryka-kod-test.md`` / ``.csv`` - research question -> metric -> code -> test.

``bomagent experiment status RUN_DIR`` writes one static ``status.html`` page built only from
the run directory (``manifest.json``, ``runs.jsonl``, ``tables/*.csv``): progress, models,
primary results, open limitations.
"""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

#: (research question, metric(s), code path, test path) - checked by a test against the repo
TRACE_ROWS: list[tuple[str, str, str, str]] = [
    (
        "PB1",
        "line_f1, designator_f1, acc_mpn, acc_value",
        "packages/py/eval/src/bomagent_eval/metrics.py",
        "packages/py/eval/tests/test_eval.py",
    ),
    (
        "PB1",
        "paired A vs B, Holm-adjusted p (primary family)",
        "packages/py/eval/src/bomagent_eval/experiment_stats.py",
        "packages/py/eval/tests/test_experiment_stats.py",
    ),
    (
        "PB2",
        "attempted_mpn_hallucination_rate, mpn_hallucination_rate",
        "packages/py/agents/src/bomagent_agents/runtime_base.py",
        "packages/py/agents/tests/test_guards.py",
    ),
    (
        "PB2",
        "detection_rate, false_alarm_rate on injected errors",
        "packages/py/eval/src/bomagent_eval/injection.py",
        "packages/py/agents/tests/test_validation.py",
    ),
    (
        "PB3",
        "llm_calls, input_tokens, output_tokens, cost_eur, wall_time_s",
        "packages/py/cli/src/bomagent_cli/experiment.py",
        "packages/py/cli/tests/test_experiment.py",
    ),
    (
        "PB3",
        "repeatability (pairwise agreement of decisions)",
        "packages/py/eval/src/bomagent_eval/stats.py",
        "packages/py/eval/tests/test_eval.py",
    ),
    (
        "H1",
        "A vs B on the pre-registered primary metrics",
        "packages/py/cli/src/bomagent_cli/experiment.py",
        "packages/py/cli/tests/test_experiment.py",
    ),
]

PRIMARY_METRICS = ("line_f1", "attempted_mpn_hallucination_rate", "cost_eur")

#: limitations shown on the status page until the thesis chapter closes them
OPEN_ITEMS = [
    "Hosted models are not deterministic even at temperature 0; repeats measure variance.",
    "Retrieval uses feature hashing and a lexical reranker (non-semantic), see manifest.",
    "Fake provider runs validate the pipeline only; they are not thesis results.",
]


def repo_root() -> Path:
    """Repository root: first parent holding ``pyproject.toml`` and ``packages/py``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (parent / "packages" / "py").is_dir():
            return parent
    raise FileNotFoundError("repository root not found")


def _load(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    runs = [
        json.loads(line)
        for line in (run_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return manifest, runs


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _prompt_texts(manifest: dict[str, Any]) -> list[tuple[str, str, str, str, bool]]:
    """(id, recorded version, sha256, text, matches current repo) per prompt of the run."""
    from bomagent_agents.prompts import load_prompt

    out = []
    for pid, recorded in sorted(manifest["prompts"].items()):
        prompt = load_prompt(pid)
        out.append((pid, recorded, prompt.sha, prompt.text, prompt.full_version == recorded))
    return out


def appendix_a(manifest: dict[str, Any]) -> str:
    lines = [
        "# Dodatek A. Prompty i profile agentów",
        "",
        "Wersja zapisana jest jako `wersja+sha8` (pierwsze 8 znaków SHA-256 treści).",
        "",
        "| prompt | wersja w przebiegu | SHA-256 | zgodny z repozytorium |",
        "|---|---|---|---|",
    ]
    prompts = _prompt_texts(manifest)
    for pid, recorded, sha, _, same in prompts:
        lines.append(f"| `{pid}` | `{recorded}` | `{sha}` | {'tak' if same else 'NIE'} |")
    for pid, recorded, _, text, same in prompts:
        lines += ["", f"## {pid} ({recorded})", ""]
        if not same:
            lines += [
                "> Uwaga: treść w repozytorium różni się od wersji użytej w przebiegu.",
                "",
            ]
        lines += ["~~~text", text, "~~~"]
    return "\n".join(lines) + "\n"


def appendix_b() -> str:
    from bomagent_bom.schema import bom_json_schema, dump

    return dump(bom_json_schema())


def appendix_c(manifest: dict[str, Any]) -> str:
    config = manifest["config"]
    retrieval = manifest.get("retrieval", {})
    sampling = manifest.get("sampling", {})
    yaml_text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    name = config["name"]
    rules = f"{manifest['rule_pack']['id']}@{manifest['rule_pack']['version']}"
    lines = [
        "# Dodatek C. Repozytorium i instrukcja uruchomienia",
        "",
        f"- Przebieg: `{name}` (utworzony {manifest.get('created_at', 'n/a')})",
        f"- Commit: `{manifest.get('commit', 'n/a')}`",
        f"- Paczka reguł: `{rules}`",
        f"- Temperatura: {sampling.get('temperature', 'n/a')}, "
        f"ziarno: {sampling.get('seed', 'n/a')}",
        f"- Migawka bazy wiedzy: `{retrieval.get('kb_snapshot_id', 'n/a')}`"
        f" ({retrieval.get('kb_files', 'n/a')} plików)",
        "",
        "## Modele",
        "",
        "| model w katalogu | identyfikator w bramce |",
        "|---|---|",
    ]
    for model, gateway in sorted(manifest.get("model_ids", {}).items()):
        lines.append(f"| `{model}` | `{gateway}` |")
    lines += [
        "",
        "## Kroki",
        "",
        "```bash",
        f"git checkout {manifest.get('commit', '<commit>')}",
        "just bootstrap",
        f"# zapisz konfigurację poniżej jako {name}.yaml",
        f"uv run bomagent experiment run {name}.yaml --out evals/reports",
        f"uv run bomagent experiment appendices evals/reports/{name}",
        f"uv run bomagent experiment status evals/reports/{name}",
        "```",
        "",
        "## Konfiguracja przebiegu",
        "",
        "```yaml",
        yaml_text.rstrip(),
        "```",
        "",
    ]
    return "\n".join(lines)


def trace_table_md() -> str:
    lines = [
        "# Tabela: pytanie badawcze, metryka, kod, test",
        "",
        "| pytanie | metryka | kod | test |",
        "|---|---|---|---|",
    ]
    lines += [f"| {q} | {m} | `{c}` | `{t}` |" for q, m, c, t in TRACE_ROWS]
    return "\n".join(lines) + "\n"


def write_appendices(run_dir: Path, out_dir: Path | None = None) -> list[Path]:
    manifest, _ = _load(run_dir)
    out = out_dir or run_dir / "appendices"
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "dodatek-a-prompty.md": appendix_a(manifest),
        "dodatek-b-schemat-bom.json": appendix_b(),
        "dodatek-c-uruchomienie.md": appendix_c(manifest),
        "tabela-pb-metryka-kod-test.md": trace_table_md(),
    }
    paths = []
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
        paths.append(out / name)
    csv_path = out / "tabela-pb-metryka-kod-test.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["research_question", "metric", "code", "test"])
        w.writerows(TRACE_ROWS)
    return [*paths, csv_path]


_CSS = (
    ":root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--warn:#a15c00}"
    "@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;"
    "--line:#333;--warn:#e0a040}}"
    "body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;"
    "max-width:60rem;margin:0 auto;padding:1rem 16px}"
    "table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem;display:block;overflow-x:auto}"
    "th,td{border-bottom:1px solid var(--line);padding:.25rem .6rem;text-align:left}"
    "h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.5rem}.mut{color:var(--mut)}"
    ".warn{color:var(--warn)}"
)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _num(value: str | None) -> str:
    try:
        return f"{float(value):.3f}" if value not in (None, "") else "n/a"  # type: ignore[arg-type]
    except ValueError:
        return str(value)


def status_html(run_dir: Path) -> str:
    manifest, runs = _load(run_dir)
    cfg = manifest["config"]
    expected = len(cfg["designs"]) * len(cfg["variants"]) * len(cfg["models"]) * cfg["repeats"]
    done = len(runs)
    statuses: dict[str, int] = {}
    for r in runs:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    real = [m for m, gw in manifest.get("model_ids", {}).items() if not gw.startswith("fake")]
    kind = "real models" if real else "fake provider (pipeline check only)"
    state = "complete" if done >= expected else "INCOMPLETE"
    rules = f"{manifest['rule_pack']['id']}@{manifest['rule_pack']['version']}"
    created = html.escape(str(manifest.get("created_at", "n/a")))
    commit = html.escape(str(manifest.get("commit", "n/a")))
    parts = [
        f"<h1>Experiment status: {html.escape(cfg['name'])}</h1>",
        f"<p class='mut'>Created {created}, commit <code>{commit}</code>, {kind}.</p>",
        "<h2>Progress</h2>",
        f"<p>{done} of {expected} planned runs recorded ({state}). Statuses: "
        f"{html.escape(json.dumps(statuses, sort_keys=True))}.</p>",
        _table(
            ["designs", "variants", "models", "repeats", "seed", "rule pack"],
            [
                [
                    len(cfg["designs"]),
                    ",".join(cfg["variants"]),
                    ",".join(cfg["models"]),
                    cfg["repeats"],
                    cfg["seed"],
                    rules,
                ]
            ],
        ),
        "<h2>Models</h2>",
        _table(
            ["catalogue", "gateway id"],
            [[m, g] for m, g in sorted(manifest.get("model_ids", {}).items())],
        ),
        "<h2>Primary metrics (mean, 95% CI)</h2>",
    ]
    variants = [
        r for r in _read_csv(run_dir / "tables" / "variants.csv") if r["metric"] in PRIMARY_METRICS
    ]
    if variants:
        parts.append(
            _table(
                ["variant", "model", "metric", "n", "mean", "ci low", "ci high"],
                [
                    [
                        r["variant"],
                        r["model"],
                        r["metric"],
                        r["n"],
                        _num(r["mean"]),
                        _num(r["ci_low"]),
                        _num(r["ci_high"]),
                    ]
                    for r in variants
                ],
            )
        )
    else:
        parts.append("<p class='mut'>No tables yet.</p>")
    paired = [r for r in _read_csv(run_dir / "tables" / "paired.csv") if r["primary"] == "True"]
    if paired:
        parts += [
            "<h2>A vs B, primary family (Holm-adjusted)</h2>",
            _table(
                ["model", "metric", "n", "diff (B-A)", "p", "p Holm"],
                [
                    [
                        r["model"],
                        r["metric"],
                        r["n"],
                        _num(r["diff"]),
                        _num(r["p_value"]),
                        _num(r["p_holm"]),
                    ]
                    for r in paired
                ],
            ),
        ]
    items = "".join(f"<li class='warn'>{html.escape(i)}</li>" for i in OPEN_ITEMS)
    parts += ["<h2>Open limitations</h2>", f"<ul>{items}</ul>"]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Experiment status {html.escape(cfg['name'])}</title><style>{_CSS}</style></head>"
        f"<body>{''.join(parts)}</body></html>\n"
    )


def write_status(run_dir: Path, out: Path | None = None) -> Path:
    target = out or run_dir / "status.html"
    target.write_text(status_html(run_dir), encoding="utf-8")
    return target


def register(app: typer.Typer) -> None:
    @app.command("appendices")
    def appendices_cmd(
        run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
        out: Annotated[Path | None, typer.Option(help="default: <run_dir>/appendices")] = None,
    ) -> None:
        """Generate thesis appendices A-C and the RQ/metric/code/test table from a run."""
        try:
            paths = write_appendices(run_dir, out)
        except FileNotFoundError as exc:
            typer.echo(f"error: not an experiment run directory: {exc}", err=True)
            raise typer.Exit(2) from exc
        for p in paths:
            typer.echo(str(p), err=True)

    @app.command("status")
    def status_cmd(
        run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
        out: Annotated[Path | None, typer.Option(help="default: <run_dir>/status.html")] = None,
    ) -> None:
        """Write a one-page static experiment status (status.html) from a run directory."""
        try:
            path = write_status(run_dir, out)
        except FileNotFoundError as exc:
            typer.echo(f"error: not an experiment run directory: {exc}", err=True)
            raise typer.Exit(2) from exc
        typer.echo(str(path), err=True)
