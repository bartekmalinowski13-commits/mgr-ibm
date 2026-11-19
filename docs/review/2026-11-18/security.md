# Security and tenant-isolation review: mgr-ibm @ f704a8f (origin/main)

Scope: services/api/src/bomagent_api (auth, authz, sso, app, ip_limits, idempotency, routers, services, repositories, samples), packages/py/db-migrations (0001-0016, rls.py, bootstrap.sql), packages/py/platform-common (db, tenancy, audit, storage, outbox, messaging/PostgresQueue, mailer, config, org_export, request_origin), all-in-one SPA CSP.
Method: read the code. Three findings were reproduced with throwaway pytest cases in a temporary `git worktree` at origin/main against the local PostgreSQL 16 + pgvector (`BOMAGENT_TEST_DATABASE_URL`). The worktree has been removed and the main working tree was not touched.

## Strengths

- **RLS model is consistent and defensive.** `tenant_table_rls` uses ENABLE + FORCE on every tenant table. `app.current_tenant_id()` returns NULL when unset, so a missing context fails closed. Every table created in migrations 0001-0016 has policies, and no table is created outside migrations. The pre-tenant lookups (API key hash, invitation email+token, SSO domain/provider, user_sub) are narrow, named SELECT policies, not BYPASSRLS.
- **Composite `(tenant_id, id)` foreign keys** (0005, 0011, 0012) close the "FK checks bypass RLS" hole. A kb trigger enforces that a document has the same owner as its rows, and the trigger runs under RLS.
- **SEC-15 (0015).** `create_organization` is SECURITY DEFINER with `search_path = pg_catalog, pg_temp`, qualified names, EXECUTE only for the platform role, and insert-only policies for the migrator. It cannot attach an owner to an existing tenant.
- **Audit log.** It is append-only (trigger plus REVOKE), the hash chain is computed in the DB under a per-tenant advisory lock, `verify_chain` refuses to run under a foreign tenant context, and anchors are exported. Audit coverage of data-changing endpoints is essentially complete; I checked every router.
- **Roles and API keys.**
  - Roles always come from the DB, never from the token. Non-members get 403 with no organisation enumeration.
  - API keys are hashed, scoped to non-admin roles at the DB CHECK level, expire and are revoked through RLS, and are revoked when their creator is demoted or removed.
- **Authentication hardening.**
  - Asymmetric JWT algorithms only.
  - The user-editable Supabase `user_metadata` claim is not trusted; the userinfo endpoint is checked instead.
  - Step-up MFA is checked after the role check.
  - SSO enforcement also checks the stored membership e-mail.
- **Object storage.** Keys are always derived from the tenant id, segments are validated, and `_check` enforces the active tenant's prefix. Client content-type is never stored.
- **Idempotency keys** are scoped per tenant and per user, cover method+path+body, and are serialised with an advisory lock.
- **Request guards.**
  - Per-IP limits never trust X-Forwarded-For.
  - Uploads must declare Content-Length.
  - NUL bytes are rejected.
  - The API CSP is `default-src 'none'`; the SPA CSP limits everything to its own origin.
  - The docs UI is off outside local/test/dev.

---

## Critical

None found.

## Important

### I-1. A removed SSO member re-joins automatically on their next request
- **Where:** `services/api/src/bomagent_api/auth.py:327-335` (`memberships()` calls `join_on_first_sign_in` on every request), `services/api/src/bomagent_api/sso.py:272-323`, `services/api/src/bomagent_api/services/members.py:218-236`.
- **What is wrong:**
  - `memberships()` is called by `org_context`, `/v1/me` and others. For any token with Cognito `identities`, it runs `join_on_first_sign_in`, which does `INSERT ... ON CONFLICT DO NOTHING`.
  - After an admin calls `DELETE /v1/members/{sub}`, the very next API call from that user re-creates the membership with the connection's `default_role`. The only trace is a `member.joined_via_sso` audit event.
  - Reproduced: remove returned 204, the next `GET /v1/projects` returned 200, and the member list contains the user again.
- **Why it matters:**
  - Removing a member is an access-control action, and an admin expects it to stick; the UI gives no hint that it does not.
  - The removal also revoked the member's API keys, so the audit trail suggests access was cut while it was not.
  - For an ISO 13485 customer this is an access-revocation failure.
- **Fix:**
  - Record removals, either as a status (`removed`/`blocked`) kept on the membership row instead of deleting it, or as a tombstone table checked by `join_on_first_sign_in`. Removed users are then not re-provisioned until an admin re-invites them or clears the block.
  - Alternatively, run JIT provisioning only on a real first sign-in, i.e. when no membership row, active or blocked, has ever existed.
  - Add a regression test: remove an SSO member, then the next request must return 403.
- **Owner-reserved:** yes. It touches `auth.py`/`sso.py`, and a status/tombstone needs a migration and an RLS/CHECK change on `tenancy.memberships`.

### I-2. A failed SSO update silently turns off enforcement and deactivates a working connection
- **Where:** `services/api/src/bomagent_api/routers/sso.py:140-171`.
- **What is wrong:**
  - When `identity_providers.apply()` fails during an update of an existing active connection (for example a typo in `metadata_url`, or a Cognito throttle), the handler sets `status='failed'` and `enforce = body.enforce and status == 'active'`, which is false.
  - It then upserts this over the previous row.
  - Cognito still holds the old, working provider. Our DB, however, now says the connection is failed and enforcement is off.
  - Reproduced: with an enforced connection, a password login was blocked with 403. A PUT with a bad URL returned 409. Afterwards the stored state was `status=failed, enforce=false`, the provider is still registered, and the same password login now gets 200.
- **Why it matters:** this fails open. One failed edit, which returns an error to the admin, removes the SSO-only requirement for every member of the verified domains (SEC-05). It also stops JIT joins and discovery, because both policies require `status='active'`.
- **Fix:**
  - On an `apply()` failure for an existing connection, keep the previous row's `status`, `enforce`, `metadata_url` and `oidc_*`. Record only the error, in `error` or an audit event, and return 422/502.
  - Write `status='failed'` only for a first-time create.
  - Add a test with `InMemoryIdentityProviders.fail_with`.
- **Owner-reserved:** no (`routers/sso.py` is not listed). The behaviour is SSO-sensitive, though, so a security review is advisable.

### I-3. Seeding sample projects at organisation creation always fails in deployed environments
- **Where:**
  - `services/api/src/bomagent_api/services/organizations.py:66-79` starts `seed_samples` with no active `TenantContext`.
  - `services/api/src/bomagent_api/samples/seeding.py:113` calls `store.put`.
  - `packages/py/platform-common/src/bomagent_common/storage.py:40-43` makes `_check` call `require_tenant()`.
- **What is wrong:**
  - `POST /v1/organizations` depends on `CurrentPrincipal`, not `OrgContext`, so no `tenant_scope` is active.
  - `make_object_store` builds a tenant-enforcing store (`enforce_tenant=True`), so the first `store.put` raises `MissingTenantContextError`. The error is caught and logged as `samples_seed_failed`, and the organisation is created without samples.
  - The test suite hides this: `test_samples.py` builds `InMemoryObjectStore(enforce_tenant=False)`.
  - Reproduced with an enforcing store: 0 projects after creation, while a manual `POST /v1/samples`, which runs under `OrgContext`, adds all 5.
- **Why it matters:**
  - This is a spec violation. DECISIONS_LOG 2026-11-12 says new organisations get sample projects, and the pilot enables it (`fly.toml`).
  - It also shows that tests turn off a tenant-isolation guard. Any other test that does the same can hide a missing context.
- **Fix:**
  - Run the seeding inside `with tenant_scope(ctx):` in `seed_samples`. Do it inside the coroutine, so that it also holds in the `create_task` copy of the context.
  - Switch `Env` in `test_samples.py` to the default `InMemoryObjectStore()`.
  - Grep the tests for `enforce_tenant=False` and justify or remove each use.
- **Owner-reserved:** no.

## Minor

### M-1. An organisation name containing CR/LF turns invitation e-mail into a 500 after commit
- **Where:**
  - `packages/py/platform-common/src/bomagent_common/mailer.py:72`: `msg["Subject"]` contains `org_name`.
  - `services/api/src/bomagent_api/services/members.py:332-336` catches only `MailError`.
- **What is wrong:**
  - `OrganizationCreate.name` allows newlines.
  - `EmailMessage` raises `ValueError` on CR/LF in a header (verified). That error is outside the try block in `_deliver` and is not a `MailError`.
  - When SMTP is configured, `POST /v1/invitations` therefore returns 500 after the invitation was committed. The inviter never sees the one-time token, and the `member.invitation_emailed` audit event is never written.
- **Why it matters:** an invitation is created and left unusable, and the audit event about it is lost.
- **Fix:** reject control characters in `OrganizationCreate.name` (and in any future rename). Also strip `\r\n` from the subject, or catch `Exception` in `_send_invitation_email` and treat it as `outcome="failed"`.
- **Owner-reserved:** no.

### M-2. Check-then-insert quota races
- **Where:** `routers/identity.py:55-57` (`MAX_OWNED_ORGANIZATIONS`) and `services/exports.py:136-138` (`MAX_EXPORTS_PER_DAY`).
- **What is wrong:** each counts and then inserts without a lock, so concurrent requests can exceed the limit. The IP burst for organisation creation is 5.
- **Fix:**
  - Organisations: take `pg_advisory_xact_lock(hashtext('owner:'||sub))` in the platform transaction before counting, or do the count inside `tenancy.create_organization`.
  - Exports: take a per-tenant advisory lock before `count_events_last_24h`.
- **Owner-reserved:** organisations, only if the count is moved into the migration function; exports, no.

### M-3. Unbounded concurrent SSE streams per user
- **Where:** `routers/runs.py:144-171`.
- **What is wrong:**
  - Each stream polls the DB every `sse_interval_s` (1 s) for up to 900 s.
  - The rate limit counts only the opening request (pilot 120/min). One user can hold hundreds of streams, each running a transaction per second against a shared pool of 5+5 connections.
- **Why it matters:** this degrades the service for every tenant, because the pool is shared.
- **Fix:** cap concurrent streams per actor and per tenant (an in-process counter, or a row in `app.rate_windows` keyed `sse:<actor>`). Alternatively, back off the polling interval for long-lived streams.
- **Owner-reserved:** no.

### M-4. Without Cognito, SSO setup reports "active" when nothing is federated
- **Where:** `app.py:333-340`.
- **What is wrong:**
  - Outside local/test without Cognito settings (the Supabase pilot), the app uses `InMemoryIdentityProviders` and `StaticTxtResolver`.
  - `PUT /v1/sso` then stores `status='active'` although no IdP exists. The Settings screen offers SSO, and domain verification can never succeed.
- **Fix:** when Cognito is not configured outside local/test, set `identity_providers=None` and make `/v1/sso` (except discovery) answer 404 or 501 `sso-unavailable`, so the UI can hide the screen.
- **Owner-reserved:** no.

### M-5. Secrets in Settings without `repr=False`
- **Where:** `app.py:117` (`oidc_userinfo_apikey`) and `app.py:163` (`llm_gateway_key`).
- **What is wrong:** other secrets (`smtp_password`, the DB URLs) use `Field(repr=False)`; these two do not. Any `repr(settings)` or a validation error message would print the LLM gateway key.
- **Fix:** `Field(default=None, repr=False)` on both.
- **Owner-reserved:** no.

### M-6. Stale policy comment for `project.delete`
- **Where:** `authz.py:28`.
- **What is wrong:** the comment says `"project.delete": ADMIN,  # sample projects only`, but since UX-03 (#66) `services/projects.delete_project` deletes any project. The migration 0014 docstring says the same.
- **Why it matters:** this is the one table meant to be reviewed as "the" policy (ADR-0005), and it misstates what admins can do.
- **Fix:** update the comment, and append a DECISIONS_LOG entry if general deletion was not already recorded there.
- **Owner-reserved:** yes (authz.py), but this is a comment only.

## Declined to judge

- **Platform role residual (0013/0015).** `bomagent_platform` can read and delete every tenant's queue rows and UPDATE every column of `tenancy.tenants`, including `plan`. This is documented as the SEC-15 residual risk and needs infrastructure separation.
- **MFA on exports and on API-key-authenticated actions.** SEC-06 explicitly excludes exports, and keys cannot hold admin roles.
- **KB documents do not count toward the storage quota.** This is an explicit DECISIONS_LOG decision (L1).
- **Trust of `client_ip_header`.** This depends on the origin being reachable only through the edge, which is deployment configuration outside this review.
- **CloudFront-Viewer-Address IPv6 format parsing** in `ip_limits.raw_client_ip`. I did not verify CloudFront's exact IPv6 format.
- **Ingest, agent and kb-indexer worker handlers and the LangGraph checkpoint serializer.** These are outside the assigned area. I only checked that the outbox and PostgresQueue envelopes bind the tenant.
- **apps/web session handling** (token in `sessionStorage`). This is owner-reserved and outside the API/DB focus.
