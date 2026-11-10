# api (`bomagent_api`)

Public REST API `/v1` (FastAPI) - contract: [`openapi.json`](openapi.json) (OpenAPI 3.1,
regenerate with `just openapi`; a test fails when it drifts).

## Endpoints
| Area | Endpoints |
|---|---|
| identity | `GET /v1/me`, `POST /v1/organizations` (onboarding: caller becomes owner) |
| projects | `GET/POST /v1/projects`, `GET /v1/projects/{id}`, `GET/POST /v1/projects/{id}/files` (multipart upload -> S3 tenant prefix -> `file.uploaded` for the sandboxed ingest-worker) |
| runs | `POST /v1/runs` (variant A/B, model from the catalogue) -> `run.requested` for agent-worker; `GET /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events` (SSE) |
| BOM | `GET /v1/runs/{id}/bom`, `GET /v1/runs/{id}/bom.csv`, `PATCH /v1/runs/{id}/bom/items/{line}` (new immutable version, user provenance, MPN correction stored as tenant knowledge) |
| audit | `GET /v1/audit-events` (filters, cursor), `GET /v1/audit-events/verify` |

## Conventions
- **Auth:** OIDC bearer JWT only (issuer, audience, expiry, JWKS). Locally/in tests a mock
  IdP (`auth_mode=local`, `POST /v1/dev/token`) - refused in any other environment.
- **Organisation:** header `X-Org-Id`; membership and roles are read from the database
  (`tenancy.memberships`), never trusted from the token. Non-member -> 403; objects of
  other organisations are invisible (RLS) -> 404.
- **RBAC:** `authz.POLICIES` (Cedar-style table: action -> roles owner/admin/engineer/reviewer/viewer).
- **Errors:** RFC 9457 `application/problem+json`; **idempotency:** `Idempotency-Key` on
  creating POSTs; **pagination:** opaque cursors; security headers on every response.
- Every mutation writes an audit event in the same transaction.

## Testing
```bash
uv run pytest services/api                 # flow, roles, tenant boundaries, OpenAPI drift
uv run pytest -m contract services/api     # Schemathesis fuzzing against the contract
```
