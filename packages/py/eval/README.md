# bomagent-eval (`bomagent_eval`)

**Responsibility:** metrics for the thesis experiment (Tab. 6.1) and regression evals.

## Public interface
- `load_reference(path)` - reference BOM CSV (one row per line, `MPN Alternates` column)
- `evaluate(predicted, reference, known_mpns=...) -> EvalReport`:
  line P/R/F1 (designator-overlap matching), designator P/R/F1, field accuracy
  (value unit-aware, footprint, MPN incl. alternates, manufacturer prefix-equivalent, DNP,
  quantity), MPN hallucination rate (MPN absent from every trusted source), usage/cost
- `inject_errors(items, n, seed)` + `detection_rate(errors, findings)` - validation
  effectiveness on injected errors
- `aggregate(reports)` (mean/stdev over N runs), `pairwise_agreement(boms)` (repeatability)
- `report_markdown()`, `comparison_markdown()` - tables for the thesis

## Testing
`uv run pytest packages/py/eval`
