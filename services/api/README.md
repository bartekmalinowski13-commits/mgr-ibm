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
  refused in any other environment. Claims are configurable for other IdPs (Supabase
  Auth in the Supabase pilot): `BOMAGENT_OIDC_EMAIL_CLAIM` (default `email`),
  `BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM` (default `email_verified`; dotted paths such as
  `user_metadata.email_verified`), `BOMAGENT_OIDC_NAME_CLAIMS` (JSON list of dotted
  paths, first non-empty wins; default `["name"]`), `BOMAGENT_OIDC_ALGORITHMS` (JSON
  list, default `["RS256"]`; only asymmetric algorithms are accepted - HS256 with a
  shared secret is refused at startup and at verification). Integrations use `Authorization: Bearer bomk_...`
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
  Uploads of an organisation are serialised by the tenant row lock, so two uploads of one
  name are deterministic (the later replaces the earlier, no orphaned object). Replacing
  a file while a run of the project is queued/running -> 409 `file-in-use`. The plan limits
  the total size of design files (`Plan.storage_bytes`, replaced files count once; over
  the limit -> 429 `quota-exceeded`, like the other plan limits).
- **Concurrency:** idempotency keys are per user and serialised; BOM edits lock the run.
  The stored request hash covers method, path and body: the same key and body on another
  endpoint -> 422 `idempotency-mismatch`.
- **Queues:** `BOMAGENT_QUEUE_BACKEND=sqs` (default; `BOMAGENT_{INGEST,RUNS,KB}_QUEUE_URL`,
  in-memory when unset in local/test) or `postgres` (`PostgresQueue` on
  `app.queue_messages`; the API only inserts, with the app role in the tenant's context).
  The outbox relay delivers to whichever backend is configured.
- **Maintenance loop:** outbox relay (a row is retried up to 10 times, then marked dead
  with `last_error` and logged as `outbox_message_dead`), deletion of sent outbox rows
  older than 7 days, stuck-run reaper.

## Sample projects

Every new organisation gets five `[Sample] ...` projects (KiCad 6/8/9, an EDIF netlist, a PDF
BOM table; CC0 data in `bomagent_api/samples/data`, also `evals/samples/`). Seeding runs under
the organisation's tenant context after `POST /v1/organizations` (best effort: it never fails
the creation): project row (`projects.sample_key`, migration 0014), files under the tenant
prefix, one outbox message per file so the sandboxed ingest-worker parses them like uploads,
audit events `project.created` and `org.samples_seeded`.

- **Idempotent:** a partial unique index `(tenant_id, sample_key)` lets a sample exist once per
  organisation; repeated or concurrent calls only add what is missing.
- **Re-add:** `POST /v1/samples` (owner) adds missing samples to an existing organisation; the
  web app shows "Add sample projects" on Home and Projects while the organisation has none.
- **Delete:** `DELETE /v1/projects/{id}` (owner/admin) works for sample projects only (409
  `not-deletable` otherwise, 409 `file-in-use` while a run is active); files, runs, BOM
  versions, pending outbox rows and stored objects go with it (object cleanup is best effort,
  the answer is always 204); the audit event records the counts. Sample projects are
  read-only: uploads are refused (409 `sample-read-only`). The ingest-worker skips a message
  whose project is gone.
- **Seeding details:** one ingest message per project, metered as uploads, shielded from
  client disconnects; `POST /v1/samples` is limited to 5 calls per minute per user.
- **Quota:** sample projects are **not** counted against the plan's project limit (and seeding is
  never refused); their files (about 100 KB) do count towards the storage limit.
- **Switch:** `BOMAGENT_SEED_SAMPLES` (`true`/`false`; unset = on in local/test/dev, off in
  staging/prod). Off also disables `POST /v1/samples` (404). The test suite pins it to `false`
  (root `conftest.py`) except in `tests/test_samples.py`.

## Testing
```bash
uv run pytest services/api                 # flow, roles, tenant boundaries, OpenAPI drift
uv run pytest services/api/tests/test_samples.py   # sample pack + seeding (PostgreSQL for the seeding tests)
uv run pytest -m contract services/api     # Schemathesis fuzzing against the contract
```
