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

Tests: `uv run pytest services/agent-worker` (PostgreSQL).
