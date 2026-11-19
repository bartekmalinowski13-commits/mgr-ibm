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
checkpoint; a younger one raises `RunInProgressError` (a `RetryLaterError`: the message is
released and redelivered when the run would count as stale, not after the queue's 1 h
visibility timeout). After `BOMAGENT_RUN_MAX_RESUMES` (3) resumes the run is failed. The final
audit event and the trace carry the resume record.

**Shutdown (deploys):** SIGTERM stops the consumer claiming new messages at once; the current
run may continue for `BOMAGENT_CONSUMER_STOP_GRACE_S` (default 20 s, inside ECS's 30 s stop
timeout), then it is cancelled and its message released with a delay of
`BOMAGENT_RUN_RESUME_STALE_S`, so it is taken over and resumed as soon as it counts as stale.
The API's reaper fails a `running` run only after `run_timeout_s` (1 h) without a start,
takeover or checkpoint, so it never races that resume. Limit without a migration: no
heartbeat column (liveness is the newest `runs.graph_checkpoints.created_at`).

**Trace size cap (DATA-01/02):** the complete trace is always written to `trace.json` in
object storage; the `runs.trace` JSONB column is capped at `BOMAGENT_RUN_TRACE_MAX_BYTES`
(default 262144 = 256 KiB, `0` = off; also read by the all-in-one process). A larger trace is
truncated deterministically by `trace_cap.cap_trace` when the run finishes: the first and last
steps are kept, the middle is replaced by one `truncated` marker step
(`detail.dropped`, `total`, `kept_head`, `kept_tail`), kept steps are never modified and
`run.resumed` records are always kept. No migration. Limit: steps appended while the run is
still `running` are not capped (bounded by the run timeout); the final write applies the cap.

Tests: `uv run pytest services/agent-worker` (PostgreSQL); `tests/test_trace_cap.py` needs none.
