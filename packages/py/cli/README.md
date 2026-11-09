# bomagent-cli (`bomagent`)

```bash
uv run bomagent parse evals/fixtures/kicad/ecg-frontend --summary
uv run bomagent bom evals/fixtures/kicad/ecg-frontend --format json --out /tmp/bom.json
uv run bomagent eval /tmp/bom.json evals/fixtures/kicad/ecg-frontend/reference_bom.csv
```
`bom` is the deterministic pipeline (parser + grouping + rules, no LLM). `run --variant A|B`
(agents, M3) and `experiment run` (M8) are added in later milestones.

Testing: `uv run pytest packages/py/cli`.
