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

## Thesis assets (TH-08/TH-09)
`bomagent experiment appendices RUN_DIR` writes appendices A (prompts with version and sha256),
B (BOM JSON Schema), C (reproduction steps) and the RQ -> metric -> code -> test table into
`RUN_DIR/appendices/`; `bomagent experiment status RUN_DIR` writes a static `status.html`
(progress, models, primary metrics) from the run's manifest and tables. Code: `thesis_assets.py`.
