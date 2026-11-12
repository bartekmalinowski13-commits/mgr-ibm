# bomagent-platform-common (`bomagent_common`)

**Responsibility:** cross-cutting runtime concerns shared by every service. No domain logic.

## Public interface
| Module | What |
|---|---|
| `tenancy` | `TenantContext` (tenant, actor, roles), `tenant_scope()`, `require_tenant()` - no "all tenants" fallback |
| `db` | `make_engine()` (psycopg 3, `hide_parameters`; URLs composed by `ServiceSettings` use `sslmode=verify-full` with `BOMAGENT_DB_SSL_ROOT_CERT`, the RDS CA bundle path, else `sslmode=require`), `tenant_transaction()` sets `app.tenant_id` via `set_config(..., true)`; `platform_transaction()`; `ping()` |
| `audit` | `emit_audit()` inside the data transaction; `verify_chain()` (+ external anchors), `chain_head()` for the Object Lock export (ADR-0011) |
| `messaging` | `Message` envelope with `tenant_id` + W3C trace carrier; `SqsQueue` (AWS), `PostgresQueue` (Supabase pilot: `app.queue_messages`, migration 0013 - producer engine = app role inserting in the message's tenant, consumer engine = platform role; visibility timeout, receive count, `dead_at` after `max_receive_count` receives, `FOR UPDATE SKIP LOCKED`, long polling by re-query, `dead_letter_count()`/`purge_dead()`), `InMemoryQueue`; `process_one()`/`consume_forever()` restore tenant + trace context, ack only on success, poison messages are dead-lettered |
| `storage` | `tenant_key()` (`tenants/{id}/...`, traversal-safe); `S3ObjectStore`/`InMemoryObjectStore` refuse keys outside the active tenant's prefix; `make_object_store(settings, bucket)` builds AWS S3 by default or an S3-compatible store (Supabase Storage) from `BOMAGENT_S3_ENDPOINT_URL`, `BOMAGENT_S3_REGION`, `BOMAGENT_S3_FORCE_PATH_STYLE` (credentials from the standard `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`; optional CRC checksums off for non-AWS endpoints) |
| `logging` | structlog JSON; drops content-like keys (`prompt`, `content`, ...), masks secrets, adds `trace_id`/`tenant_id` |
| `telemetry` | OTel tracer provider (OTLP/HTTP), FastAPI/SQLAlchemy/httpx instrumentation |
| `outbox` | transactional outbox: `enqueue()`, `deliver()` (SKIP LOCKED; after `MAX_ATTEMPTS`=10 failures a row gets `dead_at` and is no longer retried, `outbox_message_dead` is logged), `cleanup_sent()` (default retention 7 days) |
| `problems` | RFC 9457 `application/problem+json` handlers, `ProblemError` |
| `health`, `service` | `/healthz`, `/readyz`; `create_service_app()` used by all four services |

## Testing
```bash
uv run pytest packages/py/platform-common           # unit + integration (needs Postgres)
uv run pytest -m isolation                          # cross-tenant suite
```
Database fixtures: `packages/py/testing/README.md`.
