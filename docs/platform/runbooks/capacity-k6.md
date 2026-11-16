# Capacity note: k6 load scenarios (OPS-09)

**Status: no number on this page is measured.** Every figure below is a placeholder threshold
chosen to make the scenarios runnable. Replace them with measured values after the first real
run and then remove this warning. Companion to [capacity.md](capacity.md) (what limits throughput
and the monthly routine).

## What exists

`tests/load/bomagent.js` (k6) against the local compose stack with the fake LLM and the mock
IdP (`BOMAGENT_AUTH_MODE=local`). It sends traffic only to `BASE_URL` (default
`http://localhost:8000`). Never point it at production or at a shared tenant: it creates its own
organisation per run, but it does create data and consume plan limits.

| Scenario | What it does | Tag |
|---|---|---|
| `bom_read` | `GET /v1/runs/{id}/bom` of a run finished in `setup()` | `kind:read` |
| `upload` | create project + upload the four ECG KiCad fixture files | `kind:upload` |
| `run_and_sse` | `POST /v1/runs` (variant B, fake model), then follow `/events` until it ends | `kind:run_create`, `kind:sse` |

Profiles: `PROFILE=smoke` (default, 10 s, a few requests per second - checks the script) and
`PROFILE=load` (5 min, 50 reads/s, 2 uploads/s, 1 run/s - placeholder shape).

```bash
just up-core
k6 run tests/load/bomagent.js                       # smoke profile
k6 run -e PROFILE=load tests/load/bomagent.js       # longer profile
```

## Placeholder thresholds (to be replaced by measurements)

| Metric | Placeholder | Measured |
|---|---|---|
| BOM read p95 | < 1 s | not measured |
| Upload (one file) p95 | < 5 s | not measured |
| Run create p95 | < 2 s | not measured |
| Error rate on reads | < 1 % | not measured |
| Runs per hour per machine size | unknown | not measured |

With the fake LLM the run time is dominated by the platform (queues, parsers, database), not by a
model, so it gives a **lower bound** for platform overhead, not real end-to-end capacity. Real
runs also wait on the LLM gateway and its provider limits.

## Caveats that affect the numbers

- The compose stack is one machine; results do not transfer to Fly or AWS sizes. Record the
  machine size next to every figure.
- Per-IP limits are in memory per replica (see capacity.md); a single load generator hits them
  first. Expect `429` until the limits for the test organisation are raised on purpose.
- Agent concurrency (LangGraph default 8) has no per-tenant cap yet; one heavy tenant can queue
  the others (OPS-09 follow-up, not done here).

## To do after the first measured run

1. Run the `load` profile three times on a named machine size; keep the median p95.
2. Fill the Measured column and a runs-per-hour figure per size; delete the status banner.
3. Add a nightly job (GitHub Actions, compose stack, fake LLM) and fail it on the measured
   thresholds plus a margin.
4. Per-tenant LiteLLM virtual keys / parallelism limits (separate task).
