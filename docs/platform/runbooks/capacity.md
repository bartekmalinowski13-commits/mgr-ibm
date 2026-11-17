# Runbook: capacity and scaling (pilot)

Audit finding OPS-06 (capacity). Measured numbers belong to OPS-09 (k6 scenarios, not done yet).
Until then **no figure here is measured**: the limits are the configured ones and the thresholds are
starting points.

## What limits throughput

| Resource | Where configured | Symptom when exhausted |
|---|---|---|
| Fly machine CPU / RAM | `deploy/supabase/fly.toml`, `fly scale vm`, `fly scale count` | high latency, OOM restarts (parsers are the heavy part) |
| Agent concurrency (LangGraph default 8, no per-tenant cap) | agent worker settings | runs queue up; the reaper marks runs older than `run_timeout_s` as failed |
| Database connections | Supavisor limit of the Supabase plan; `BOMAGENT_DB_POOL_SIZE` (app 5 + 5 overflow, platform 2 + 2) | pool errors, `/readyz` red |
| Postgres size / IOPS | Supabase plan | slow queries; `audit.events`, queue and run tables grow fastest |
| LLM gateway budget and provider limits | LiteLLM virtual key (lifetime budget, 75-day expiry, `key-rotation.md`) | 4xx/429 from the gateway, runs failing with LLM errors |
| Storage | Supabase plan quota | upload failures |

## Routine check (monthly, together with the restore drill)

- Database size, the five largest tables, growth per month.
- Peak connection count versus the plan limit; keep the peak below 70%.
- Queue depth and age and dead rows (`app.queue_messages`); runs per day and failure rate.
- LLM spend versus the key budget and the provider quota.

## Row growth caps

- `runs.runs.trace`: capped at the application level by `BOMAGENT_RUN_TRACE_MAX_BYTES` (default
  262144 bytes, `0` = off). On a finished run an oversized trace keeps its first and last steps and
  one `truncated` marker step with the dropped count; the complete trace stays in
  `tenants/{tenant}/runs/{run_id}/trace.json`. No migration or RLS change (audit DATA-01/02). Rows
  written before the cap are not rewritten.

## Scaling actions

1. More machines: `fly scale count 2`. Per-IP limits are in memory per replica (effective limit = rule x replicas, DECISIONS_LOG SEC-03), so check ARCH-02/03 first.
2. Larger machine: `fly scale vm <size>`.
3. Raise the Supabase compute size / connection limit before raising pool sizes.
4. Protect other tenants from a heavy one: lower that tenant's plan limits or gateway budget (OPS-09 adds per-tenant parallelism limits).
5. Record the change and the reason in the ops log.

## Not yet known (owner / OPS-09)

Runs per hour per machine size, p95 latencies, and the point at which the Postgres-backed queues
should give way to SQS or another broker. Write the measured numbers here after the first k6 run.
