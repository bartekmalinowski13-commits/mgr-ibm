# bomagent-cli (`bomagent`)

```bash
uv run bomagent parse evals/fixtures/kicad/ecg-frontend --summary
uv run bomagent bom evals/fixtures/kicad/ecg-frontend --format json --out /tmp/bom.json
uv run bomagent eval /tmp/bom.json evals/fixtures/kicad/ecg-frontend/reference_bom.csv
```
`bom` is the deterministic pipeline (parser + grouping + rules, no LLM). `run --variant A|B`
(agents, M3) and `experiment run` (M8) are added in later milestones.

## `bomagent-ops` (OPS-03, read-only)
Local operator helpers, no cloud or database access: `bomagent-ops env` (BOMAGENT_* settings,
secrets hidden) and `bomagent-ops queries [NAME]` (read-only SQL for stuck outbox rows and
dead-lettered queue messages, to run inside one tenant's context). Requeue/purge are not
provided yet: they must run under RLS with an audit event.

Testing: `uv run pytest packages/py/cli`.

## Experiment (`bomagent experiment run CONFIG.yaml`)
The matrix (designs x models x variants x repetitions, plus error injection) is crash-safe:
`manifest.json` is written before the first run (commit, dirty flag, run `budget`,
`minimum_run_timeout_s` per model), and every run / validation baseline / injection trial is
appended to `runs.jsonl` / `injection_baselines.jsonl` / `injection.jsonl` (BOMs under
`boms/`) as soon as it is paid for. Running the same command again resumes: finished cells
are skipped and never re-billed. A restart is refused when the configuration, budget, prompt
versions, rule pack, KB snapshot or model entries changed, and when the commit changed unless
`--allow-code-drift` is given (recorded; `report.md` lists the commits of the runs).
An exception inside a run is recorded (`status: error`, exception type) and scored like a
failed run (empty BOM with the spend so far), so the design stays in the paired test; the
report gives pairs and dropped pairs per metric. A
validator call that fails is a failed trial (no rates), not a miss; calls with estimated or
unbilled usage are counted per run (`billing`) and in the report's cost-accounting table.
`budget.timeout_s` (default 3600 s) must cover one call of every sequential step at its
per-call budget, else the run is refused. With `cassettes:` a real model replays recordings
only (`bomagent record --model <id>` first).

## Thesis assets (TH-08/TH-09)
`bomagent experiment appendices RUN_DIR` writes appendices A (prompts with version and sha256),
B (BOM JSON Schema), C (reproduction steps) and the RQ -> metric -> code -> test table into
`RUN_DIR/appendices/`; `bomagent experiment status RUN_DIR` writes a static `status.html`
(progress, models, primary metrics) from the run's manifest and tables. Code: `thesis_assets.py`.
