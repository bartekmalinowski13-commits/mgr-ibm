# ingest-worker

Consumes `file.uploaded` from the `ingest` queue: loads the file from the tenant prefix,
parses it in the resource-limited sandbox (`bomagent_cad.sandbox`) and stores the parse
summary on `projects.files` in the message's tenant context (RLS).

Config: `BOMAGENT_DATABASE_URL`, `BOMAGENT_QUEUE_URL`, `BOMAGENT_FILES_BUCKET`.
Health: `/healthz`, `/readyz`.

**Queue backend:** `BOMAGENT_QUEUE_BACKEND=sqs` (default, AWS: `BOMAGENT_QUEUE_URL`) or
`postgres` (Supabase pilot: `app.queue_messages`, queue `BOMAGENT_QUEUE_NAME`, default
`ingest`; consumed with the platform role, so `BOMAGENT_PLATFORM_DATABASE_URL` or
`BOMAGENT_PLATFORM_DATABASE_PASSWORD` is required). Without either the worker runs in
health-only mode.

Tests: `uv run pytest services/ingest-worker tests/services` (PostgreSQL).
