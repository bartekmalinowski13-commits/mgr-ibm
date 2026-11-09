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

Tests: `uv run pytest services/kb-indexer`.
