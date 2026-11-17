# kb-indexer

Worker consuming the `kb` SQS queue: loads the uploaded file from S3 (tenant prefix
enforced), extracts text, chunks, embeds through the gateway and indexes it
(`bomagent_kb`). Tenant documents use the application role in the message's tenant
context; the global corpus uses the platform role and is accepted only from the
platform pseudo-tenant with `actor_type=system`. Corrupt files mark the document
`failed`; transient errors are retried and dead-lettered.

Health: `/healthz`, `/readyz`. Config: `BOMAGENT_DATABASE_URL`,
`BOMAGENT_PLATFORM_DATABASE_URL`, `BOMAGENT_QUEUE_URL`, `BOMAGENT_FILES_BUCKET`,
`BOMAGENT_GLOBAL_BUCKET`, `BOMAGENT_LLM_GATEWAY_URL/KEY`, `BOMAGENT_EMBEDDING_MODEL`,
`BOMAGENT_USE_DOCLING`.

**Queue backend:** `BOMAGENT_QUEUE_BACKEND=sqs` (default, AWS: `BOMAGENT_QUEUE_URL`) or
`postgres` (Supabase pilot: `app.queue_messages`, queue `BOMAGENT_QUEUE_NAME`, default
`kb`; consumed with the platform role, so `BOMAGENT_PLATFORM_DATABASE_URL` or
`BOMAGENT_PLATFORM_DATABASE_PASSWORD` is required). Without either the worker runs in
health-only mode.

Tests: `uv run pytest services/kb-indexer`.

## Organisation export (SEC-14)

`org.export.requested` on the same `kb` queue (no extra queue to provision) builds the ZIP of an
organisation (`bomagent_kb_indexer.export`): projects with file metadata, runs, every BOM version
(JSON + CSV), own knowledge-base document metadata, the audit log. Stored under
`tenants/{id}/exports/{job}/`; state in `status.json` there. Uploaded design files and document
bodies are not included yet. Tests: `test_export_unit.py` (unit), `services/api/tests/test_org_export.py` (DB, CI).
