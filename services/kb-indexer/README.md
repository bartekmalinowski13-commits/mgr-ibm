# kb-indexer

Worker consuming the `kb` SQS queue: loads the uploaded file from S3 (tenant prefix
enforced), extracts text, chunks, embeds through the gateway and indexes it
(`bomagent_kb`). Tenant documents use the application role in the message's tenant
context; the global corpus uses the platform role and is accepted only from the
platform pseudo-tenant with `actor_type=system`.

Documents are untrusted customer files: text extraction (pypdf, or Docling with
`BOMAGENT_USE_DOCLING`) runs in the resource-limited sandbox child of `bomagent_cad.sandbox`
(`bomagent_kb_indexer.sandbox`, child `_extract_child`), off the event loop. Limits:
`BOMAGENT_KB_EXTRACT_MEMORY_MB` (default 1024 - raise it for Docling),
`BOMAGENT_KB_EXTRACT_CPU_SECONDS` (60), `BOMAGENT_KB_EXTRACT_TIMEOUT_SECONDS` (90).
Corrupt, hostile or over-limit files mark the document `failed` with the reason (audited as
`kb.document.failed`) and the message is acknowledged; transient errors (storage, database)
are retried and dead-lettered, and the API's maintenance sweep fails documents still
`pending` after the retry window. KB uploads are not malware-scanned yet.
Tests: `tests/test_extract_sandbox.py` (no database), `tests/test_handler.py`.

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
