# agent-worker

Consumes `run.requested` from the `runs` SQS queue: loads the design files from the
tenant prefix in S3, parses them, runs variant A or B (`bomagent_agents`) with
tenant-scoped retrieval (RLS), stores `bom.json` and `trace.json` under
`tenants/{tenant}/runs/{run_id}/` and records `run.completed` in the tenant's audit chain.
Keys outside the tenant prefix are rejected. Without a configured gateway the worker uses
the fake provider (local/test only).

Config: `BOMAGENT_DATABASE_URL`, `BOMAGENT_QUEUE_URL`, `BOMAGENT_FILES_BUCKET`,
`BOMAGENT_LLM_GATEWAY_URL/KEY`, `BOMAGENT_EMBEDDING_MODEL`. Health: `/healthz`, `/readyz`.
Run tables, progress streaming (SSE) and run status in the API come with M4.

**Queue backend:** `BOMAGENT_QUEUE_BACKEND=sqs` (default, AWS: `BOMAGENT_QUEUE_URL`) or
`postgres` (Supabase pilot: `app.queue_messages`, queue `BOMAGENT_QUEUE_NAME`, default
`runs`; consumed with the platform role, so `BOMAGENT_PLATFORM_DATABASE_URL` or
`BOMAGENT_PLATFORM_DATABASE_PASSWORD` is required). Without either the worker runs in
health-only mode.

**Resume (ARCH-05):** a redelivered `run.requested` for a run still `running` whose last
checkpoint/state write is older than `BOMAGENT_RUN_RESUME_STALE_S` (default 1200 s, above the longest single LLM call) is taken
over (compare-and-swap on `started_at`, audit `run.resumed`) and continued from the last
checkpoint; a younger one raises `RunInProgressError` (not acked, retried later). After
`BOMAGENT_RUN_MAX_RESUMES` (3) resumes the run is failed. The final audit event and the
trace carry the resume record. Limits without a migration: no heartbeat column (liveness is
the newest `runs.graph_checkpoints.created_at`), and the reaper still fails runs by
`started_at` (reset on takeover).

**Metering of failed runs:** the spend so far is taken from every finished step (the
`on_step` progress callback, also called by a step that raises), so a run that fails with a
non-LLM exception inside the runtime still meters the calls it made, not 0. Timed-out calls
are metered at the client's estimate (`LlmError.billing`, see `packages/py/llm`).

**Trace size cap (DATA-01/02):** the complete trace is always written to `trace.json` in
object storage; the `runs.trace` JSONB column is capped at `BOMAGENT_RUN_TRACE_MAX_BYTES`
(default 262144 = 256 KiB, `0` = off; also read by the all-in-one process). A larger trace is
truncated deterministically by `trace_cap.cap_trace` when the run finishes: the first and last
steps are kept, the middle is replaced by one `truncated` marker step
(`detail.dropped`, `total`, `kept_head`, `kept_tail`), kept steps are never modified and
`run.resumed` records are always kept. No migration. Limit: steps appended while the run is
still `running` are not capped (bounded by the run timeout); the final write applies the cap.

Tests: `uv run pytest services/agent-worker` (PostgreSQL); `tests/test_trace_cap.py` needs none.
