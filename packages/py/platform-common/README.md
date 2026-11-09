# bomagent-platform-common (`bomagent_common`)

**Responsibility:** cross-cutting runtime concerns shared by every service. No domain logic.

## Public interface
| Module | What |
|---|---|
| `tenancy` | `TenantContext` (tenant, actor, roles), `tenant_scope()`, `require_tenant()` - no "all tenants" fallback |
| `db` | `make_engine()` (psycopg 3, `hide_parameters`), `tenant_transaction()` sets `app.tenant_id` via `set_config(..., true)`; `platform_transaction()`; `ping()` |
| `audit` | `emit_audit()` inside the data transaction; `verify_chain()` (+ external anchors), `chain_head()` for the Object Lock export (ADR-0011) |
| `messaging` | `Message` envelope with `tenant_id` + W3C trace carrier; `SqsQueue`, `InMemoryQueue`; `process_one()`/`consume_forever()` restore tenant + trace context, ack only on success, poison messages go to the DLQ |
| `storage` | `tenant_key()` (`tenants/{id}/...`, traversal-safe); `S3ObjectStore`/`InMemoryObjectStore` refuse keys outside the active tenant's prefix |
| `logging` | structlog JSON; drops content-like keys (`prompt`, `content`, ...), masks secrets, adds `trace_id`/`tenant_id` |
| `telemetry` | OTel tracer provider (OTLP/HTTP), FastAPI/SQLAlchemy/httpx instrumentation |
| `problems` | RFC 9457 `application/problem+json` handlers, `ProblemError` |
| `health`, `service` | `/healthz`, `/readyz`; `create_service_app()` used by all four services |

## Testing
```bash
uv run pytest packages/py/platform-common           # unit + integration (needs Postgres)
uv run pytest -m isolation                          # cross-tenant suite
```
Database fixtures: `packages/py/testing/README.md`.
