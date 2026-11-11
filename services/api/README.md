# api (`bomagent_api`)

Public REST API `/v1` (FastAPI) - contract: [`openapi.json`](openapi.json) (OpenAPI 3.1,
regenerate with `just openapi`; a test fails when it drifts).

## Endpoints
| Area | Endpoints |
|---|---|
| identity | `GET /v1/me`, `POST /v1/organizations` (onboarding with verified e-mail: caller becomes owner) |
| members | `GET /v1/members`, `PATCH/DELETE /v1/members/{sub}` (only owners touch the owner role; the last owner stays), `GET/POST /v1/invitations`, `DELETE /v1/invitations/{id}`, `POST /v1/invitations/accept` (secret token + verified matching e-mail) |
| API keys | `GET/POST /v1/api-keys`, `POST /v1/api-keys/{id}/rotate`, `DELETE /v1/api-keys/{id}` (admins; scope engineer/reviewer/viewer; secret shown once, SHA-256 stored) |
| projects | `GET/POST /v1/projects`, `GET /v1/projects/{id}`, `GET/POST /v1/projects/{id}/files` (multipart upload -> S3 tenant prefix -> `file.uploaded` for the sandboxed ingest-worker) |
| runs | `POST /v1/runs` (variant A/B, model from the catalogue) -> `run.requested` for agent-worker; `GET /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events` (SSE) |
| BOM | `GET /v1/runs/{id}/bom`, `GET /v1/runs/{id}/bom.csv`, `PATCH /v1/runs/{id}/bom/items/{line}` (new immutable version, user provenance, MPN correction stored as tenant knowledge) |
| SSO | `GET/PUT/DELETE /v1/sso` (owners/admins: SAML 2.0 or OIDC identity provider federated in Cognito; OIDC client secret goes to Cognito only), `POST /v1/sso/domains`, `POST /v1/sso/domains/{domain}/verify` (DNS TXT `_bomagent-verify.<domain>`), `DELETE /v1/sso/domains/{domain}`, `GET /v1/sso/discover?email=` (public, sign-in screen). First sign-in through the provider with a verified-domain e-mail creates the membership (default role); `enforce` requires SSO for those domains (owners exempt). See `bomagent_api.sso` |
| audit | `GET /v1/audit-events` (filters, cursor), `GET /v1/audit-events/verify` |

## Conventions
- **Auth:** OIDC bearer JWT (issuer, audience, expiry, JWKS; required settings outside
  local/test). Locally/in tests a mock IdP (`auth_mode=local`, `POST /v1/dev/token`) -
  refused in any other environment. Integrations use `Authorization: Bearer bomk_...`
  (organisation API key, bound to its organisation; not accepted by user-only endpoints
  such as `/v1/me`). Key and invitation lookups stay inside RLS (hash-matching policies).
- **Organisation:** header `X-Org-Id`; membership and roles are read from the database
  (`tenancy.memberships`), never trusted from the token. Non-member -> 403; objects of
  other organisations are invisible (RLS) -> 404.
- **RBAC:** `authz.POLICIES` (Cedar-style table: action -> roles owner/admin/engineer/reviewer/viewer).
- **Errors:** RFC 9457 `application/problem+json`; **idempotency:** `Idempotency-Key` on
  creating POSTs; **pagination:** opaque cursors; security headers on every response.
- Every mutation writes an audit event in the same transaction.
- **Uploads:** `Content-Length` required and checked before the body is read (64 MB);
  stored as `application/octet-stream`; a replaced file's old object is deleted.
- **Concurrency:** idempotency keys are per user and serialised; BOM edits lock the run.

## Testing
```bash
uv run pytest services/api                 # flow, roles, tenant boundaries, OpenAPI drift
uv run pytest -m contract services/api     # Schemathesis fuzzing against the contract
```
