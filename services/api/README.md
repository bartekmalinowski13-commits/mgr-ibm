# bomagent-api (`bomagent_api`)

**Responsibility:** public REST API v1 (OpenAPI 3.1 contract in `openapi.json`).

## Endpoints (M4 part 1)
| Method | Path | Role |
|---|---|---|
| POST/GET | `/v1/projects` | write / read |
| POST | `/v1/projects/{id}/designs` → presigned upload URLs | write |
| POST | `/v1/designs/{id}/complete` → queue parsing (ingest-worker) | write |
| GET | `/v1/designs/{id}` | read |
| POST | `/v1/runs` (`Idempotency-Key` required) → queue run (agent-worker) | write |
| GET | `/v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/bom`, `/v1/runs/{id}/trace` | read |
| GET | `/v1/runs/{id}/events` (SSE) | read |
| GET | `/v1/audit/events` | owner/admin/reviewer |

Auth: OIDC bearer JWT (`sub`, `org_id`, `roles`); `BOMAGENT_AUTH_MODE=dev` only locally.
Errors: RFC 9457 problem+json. Objects of other tenants: 404.

## Testing
`uv run pytest services/api` (Postgres: see `packages/py/testing`). Contract: `uv run python tools/export_openapi.py` after API changes.
