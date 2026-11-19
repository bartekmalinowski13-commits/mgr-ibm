# Code review: REST API correctness and data layer (services/api, bom-core, platform-common)

Reviewed at `origin/main` = `f704a8f`. Method: read the routers, services, repositories, pagination,
idempotency, outbox, queue, maintenance, exports, problem handlers, telemetry, bom-core model/export/diff.
Ran probes against a real PostgreSQL (Testcontainers) in a throwaway worktree `/tmp/rev-api` (since removed).
Also regenerated the OpenAPI document and compared it with `services/api/openapi.json`: **identical**.

## Strengths

- **Committed contract matches the code.** `openapi_document()` output equals `services/api/openapi.json` byte for byte. Every router declares its problem+json error codes.
- **Idempotency is solid.** Keys are scoped per tenant (RLS) and per user (hash of actor + key). The request hash covers method, path and body. A transaction-scoped advisory lock serialises concurrent requests with the same key, and the key is stored in the same transaction as the created row. A 24 h sweep keeps the table bounded.
- **Keyset pagination is correct.** It orders on `(created_at DESC, id DESC)` with a tuple predicate, the cursor is opaque, `limit + 1` decides whether a next page exists, and the limit is clamped to 1..100. A bad cursor gives a 400 problem+json (projects, runs, invitations, KB, API keys).
- **Transactional outbox done properly.** Rows are written in the business transaction and sent after the commit (best effort), then retried by the relay. `FOR UPDATE SKIP LOCKED`, the dead-letter rule (attempts plus age) and the tenant check on the envelope (`_envelope`) are all in place. The Postgres queue copies SQS semantics (visibility timeout, redrive, stale-receipt ack).
- **Quota checks serialise on a tenant row lock.** Uploads use `ON CONFLICT` upserts. BOM edits serialise with `lock_run`. Member and owner changes use row locks.
- **Audit coverage is complete.** Every data-changing path I traced emits an audit event inside its own transaction: projects, files, runs, cancel, BOM edits, evaluation, export, members, invitations, API keys, samples, the reaper and KB documents.
- **Export hardening is good.** CSV export guards against formula injection. XLSX export writes inline strings, never formulas, and strips XML-illegal control characters. `version_content` binds the version number untyped, so an oversized number gives 404, not 500.

## Issues

### Critical

None found.

### Important

**I1. Unhandled exceptions are not RFC 9457 and lose the security headers.**
- Where: `packages/py/platform-common/src/bomagent_common/problems.py:65-95` (no `Exception` handler); `services/api/src/bomagent_api/app.py:420-427` (`security_headers` uses `@app.middleware`, which sits inside `ServerErrorMiddleware`).
- What is wrong: any error that is not a `ProblemError`, `HTTPException` or validation error falls through to Starlette's default handler. Two probes showed this:
  - `GET /v1/audit-events?cursor=²` returned `500 text/plain "Internal Server Error"` with **no** `X-Content-Type-Options`, `Cache-Control: no-store`, CSP or HSTS headers.
  - Four concurrent identical KB uploads returned one `500 text/plain`.
- Why it matters: it breaks the API convention (RFC 9457 for all errors). Generated clients and the web app cannot parse these errors. The security headers are missing on exactly the responses that come from unexpected states.
- Fix:
  1. Register `app.add_exception_handler(Exception, _internal)` in `install_problem_handlers`. It should return `Problem(type=PROBLEM_BASE+"internal", title="Internal Server Error", status=500)` and log the exception with the request id.
  2. Either set `SECURITY_HEADERS` in that handler, or turn `security_headers` into a pure ASGI middleware added last (outermost), so it also wraps `ServerErrorMiddleware` output.
  3. Add a contract test that forces a 500 and asserts the problem+json media type and the headers.
- Owner-reserved: no.

**I2. Audit-log cursor is not validated and is not opaque.**
- Where: `services/api/src/bomagent_api/repositories/audit.py:21-23`.
- What is wrong:
  - `int(cursor) if cursor.isdigit() else 0`. `str.isdigit()` accepts Unicode digits such as `²`, which `int()` rejects, so the request gives a 500 (verified).
  - Any other bad cursor (`garbage`) silently returns `200 {"items": [], "next_cursor": null}` (verified). A client cannot tell this from "no more events".
  - The cursor is a raw `seq`, unlike every other list endpoint.
- Why it matters: this is a status-code defect on a compliance endpoint, it is inconsistent with the pagination contract ("cursors are opaque"), and it is a 500 that any reviewer-role user can trigger.
- Fix:
  - Parse with `cursor.isascii() and cursor.isdigit()`, otherwise raise `ProblemError(400, ..., slug="invalid-cursor")`.
  - Better: encode the cursor opaquely (base64 of the `seq`) through a helper in `pagination.py`, so all list endpoints share one decode-and-400 path.
  - Add tests for `²`, `abc` and an empty cursor.
- Owner-reserved: no.

**I3. KB uploads bypass the plan storage quota.**
- Where: `services/api/src/bomagent_api/services/kb.py:62-115`, compared with `services/api/src/bomagent_api/plans.py` `check_storage` (sums `projects.files` only).
- What is wrong: `POST /v1/kb/documents` stores up to 32 MB per call under the tenant prefix. It never calls `plan_of(lock=True)` or a storage check, and `kb.documents.size_bytes` is not counted in `Plan.storage_bytes`. The only limit is the per-user request rate (pilot: 120/min, about 3.8 GB/min).
- Why it matters: the plan limits that ARCHITECTURE §5 and SECURITY require cannot be enforced. One engineer-role user or API key can grow object storage and DB rows without bound. Every indexed document also costs embedding calls, and those costs are not counted against the LLM budget at upload time.
- Fix:
  - Make `check_storage` count `projects.files` plus non-superseded tenant-scope `kb.documents.size_bytes`, or add a separate `kb_storage_bytes` limit to `Plan`.
  - In `upload_document`, call `plan_of(conn, lock=True)` and the check **before** `store.put`. To do that, move the put inside the transaction, as `upload_file` does, or check first and put afterwards.
  - Add a test that the quota is exceeded through KB uploads.
- Owner-reserved: no. A new `Plan` field is plain code; no migration is needed.

**I4. Duplicate KB uploads: a 500 under concurrency, and repeated indexing jobs with orphaned objects while pending.**
- Where: `packages/py/kb/src/bomagent_kb/store.py:145-178` (SELECT-then-INSERT, no `ON CONFLICT`, unique index `documents_dedupe`); `services/api/src/bomagent_api/services/kb.py:99-114`.
- What is wrong:
  - (a) Two concurrent uploads of the same content both pass the SELECT. The second INSERT violates `documents_dedupe`, the `IntegrityError` is not mapped, and the client gets a 500 (verified: three 201s and one 500).
  - (b) A sequential duplicate uploaded while the original is still `pending` takes the branch `doc["status"] == "pending" and doc["indexed_at"] is None`. It enqueues a **second** `kb.document.uploaded` message for the same `document_id`, with the **new** object key. Because `outbox_id` is then not `None`, the new object is kept. Verified: two queue messages with different `object_key`s for one document id.
  - That second object is never referenced by `kb.documents.object_key`, so no cleanup path will ever delete it. The document is also indexed twice; indexing is idempotent, so this is only wasted work.
  - A duplicate also returns `201 Created` although nothing was created.
- Why it matters: a 500 on a benign race, orphaned tenant objects (a storage leak that GDPR deletion will not reach through the row), and duplicate embedding cost.
- Fix:
  - In `add_document`, use `INSERT ... ON CONFLICT DO NOTHING RETURNING id`, and fall back to a SELECT of the existing id. Return `(id, created: bool)`.
  - In the API, enqueue only when `created` is true. Otherwise delete the new object.
  - Return 200 for an existing document. FastAPI needs a `Response` parameter to set the status, and both 200 and 201 must be declared in OpenAPI.
- Owner-reserved: no.

**I5. SQLAlchemy is never auto-instrumented, and background data paths have no spans.**
- Where:
  - `packages/py/platform-common/src/bomagent_common/telemetry.py:112` defines `instrument_sqlalchemy`, but nothing calls it. A grep of the whole repository confirms this.
  - `services/api/src/bomagent_api/maintenance.py:108-142` (`sweep`) and `packages/py/platform-common/src/bomagent_common/outbox.py:229-291` (`deliver`) open no span.
- What is wrong: ARCHITECTURE §10 and ADR-0010 require auto-instrumentation of FastAPI, SQLAlchemy and httpx. Only FastAPI and httpx are wired. The maintenance loop changes data (it reaps runs and emits `run.failed` audit events, expires keys, relays outbox rows) outside any request, so those writes produce no trace.
- Why it matters: this misses the Definition of Done item "OTel traces for new paths". Slow queries, lock waits on the tenant row and outbox relay failures cannot be seen in Grafana or X-Ray.
- Fix:
  - Call `instrument_sqlalchemy(engine)` in `create_app` for `engine` and `platform_engine` when they are not `None`, and do the same in the workers.
  - Wrap each tenant iteration of `sweep` in `tracer.start_as_current_span("maintenance.sweep_tenant", attributes={"tenant.id": ...})`.
  - Wrap `deliver` in a `PRODUCER` span (`messaging.operation.type=send`).
- Owner-reserved: no.

### Minor

**M1. Corrected BOM versions inherit the parent's `id` and `created_at`.**
- Where: `services/api/src/bomagent_api/services/runs.py:508-513`.
- What is wrong: `bom.model_copy(update={"items": items})` keeps `BomVersion.id` and `created_at`, so version 2, 3 and so on of a run all carry version 1's document id and generation time (verified). `model_copy` also skips validation, so the patched fields are not stripped or validated by `BomItem` rules.
- Why it matters: content ids are expected to be unique across immutable versions (thesis traceability and export). `bom.created_at` in the API, in exports and in the org export is misleading.
- Fix: `new_bom = BomVersion.model_validate(bom.model_dump() | {"items": [...], "id": uuid4(), "created_at": now})`, and build `new_item` with `BomItem.model_validate(...)` as well.
- Owner-reserved: no.

**M2. Idempotent replay can be refused by a pre-check.**
- Where: `services/api/src/bomagent_api/services/runs.py:205-209`.
- What is wrong: `resolve_runtime` and `check_model_allowed` run **before** `idempotency.replay`. A retry with the same key, after the model has been disabled in the catalogue, gets a 422 instead of the stored 202.
- Fix: run the replay first and the validation after it, as `rerun` already does at line 243 and following.
- Owner-reserved: no.

**M3. The upload path can return a 500 after a successful commit.**
- Where: `services/api/src/bomagent_api/services/projects.py:352`.
- What is wrong: `await store.delete(previous.object_key)` runs after the commit with no error handling. If S3 is briefly down, the client gets a 500 although the file row, audit event and outbox row are committed. `deliver_now` is also skipped, so the relay sends the message about 30 s later.
- Fix: use `delete_objects(store, ctx.tenant_id, [previous.object_key], file_id=...)` (best effort and logged), as `delete_file` does.
- Owner-reserved: no.

**M4. An S3 upload of up to 64 MB runs while the tenant's quota row lock is held.**
- Where: `services/api/src/bomagent_api/services/projects.py:297` (`plan_of(lock=True)`) through `:311` (`store.put_file`).
- What is wrong: the `FOR NO KEY UPDATE` on `tenancy.tenants` is held while the object is streamed to the store. Every other upload, project creation (`check_new_project`) and run start (`check_new_run`) of the organisation waits behind it.
- Fix: do the S3 put before taking the lock (the key is already unique), then take the lock, check, and upsert. On failure, delete the object, as the existing `except` already does.
- Owner-reserved: no.

**M5. The org export daily cap is racy, and a failed start leaves a ghost job.**
- Where: `services/api/src/bomagent_api/services/exports.py:70-80`.
- What is wrong:
  - `count_events_last_24h` is read without a lock, so concurrent POSTs can exceed `MAX_EXPORTS_PER_DAY`.
  - `write_status` stores `status.json` (`queued`) **before** the commit. If the transaction then fails (for example, the idempotency insert), `GET .../export/{id}` reports `queued` for ever.
- Fix: take `plan_of(conn, lock=True)` (or an advisory lock) before counting. Write the status after the audit and outbox rows, as the last step before commit, or have the worker treat an unknown job as failed. The current comment's invariant still holds if the status is written last before commit.
- Owner-reserved: no.

**M6. Outbox delivery needs two pooled connections at once on the Postgres queue backend (the pilot).**
- Where: `packages/py/platform-common/src/bomagent_common/outbox.py:58-71` holds a transaction with row locks while `PostgresQueue.send` (`messaging.py:220`) opens a second transaction on the same app engine. The engine is passed as `producer_engine` in `app.py:320`, and its pool is 5 + 5 overflow.
- What is wrong: with 10 or more concurrent `deliver_now` or relay calls, every pooled connection is held by an outer transaction that waits for a second one. That stalls for the pool timeout (30 s), and then every send counts as a failed attempt.
- Fix: in `deliver`, collect the rows, send each message through the **same** connection when the queue is a `PostgresQueue` (add `send_in(conn, message)`), or release the outer transaction before sending (claim with a lease column).
- Owner-reserved: no.

**M7. One failing tenant stops the maintenance sweep for every tenant after it.**
- Where: `services/api/src/bomagent_api/maintenance.py:123-139`.
- What is wrong: only anchor export has its own error handling. An exception in `deliver`, `cleanup_sent`, `reap_stuck_runs` or the expiry functions for tenant *k* aborts the whole sweep. A persistent fault in one tenant starves the relay and the reaper of all later tenants.
- Fix: wrap each tenant's block in `try/except Exception: log.exception(..., tenant_id=...)` and carry on.
- Owner-reserved: no.

**M8. The member list silently truncates at 1000 rows.**
- Where: `services/api/src/bomagent_api/services/members.py:42,84-85`.
- What is wrong: it returns `Page(next_cursor=None)` even when there are more than 1000 members, so data is missing without any signal.
- Fix: paginate with a keyset on `(created_at, user_sub)`, or fetch `limit + 1` and return a 409 or a `next_cursor`.
- Owner-reserved: no.

**M9. Small contract gaps in the OpenAPI document.**
- `limit` on all list endpoints (`routers/*.py`, e.g. `projects.py:37`) has no `minimum`/`maximum`, but the server clamps to 1..100. Use `Annotated[int, Query(ge=1, le=100)]`, or document the clamp.
- The `Idempotency-Key` header has no `minLength: 8` / `maxLength: 255`, which `idempotency.py:45` enforces. Use `Header(min_length=8, max_length=255)`.
- 411 (`Length Required`, `app.py:410-412`) is not declared on the upload endpoints.
- `POST /v1/organizations` is a creating POST without `Idempotency-Key`. A retry gets `409 slug-taken` for the caller's own organisation.
- Owner-reserved: no.

## Declined to judge

- **Owner-reserved files.** I did not review `auth.py`, `authz.py`, `sso.py`/`routers/sso.py`, the RLS policies or migrations beyond reading the KB dedupe index, `still_authorized` in SSE, or the MFA handler. Note that I1's fix touches `problems.py` (platform-common) and `app.py` middleware, not `auth.py`.
- **429 for plan quotas.** Plan quotas (projects, runs, storage) return `429 quota-exceeded` without `Retry-After`. That is a design choice recorded in `plans.py`; whether 403 or 409 would be better is a spec question, not a defect.
- **Worker-side consumers.** I did not judge whether the ingest, agent and kb-indexer consumers are idempotent under at-least-once redelivery. That is outside this area.
- **Sweep scalability.** The sweep runs about five transactions per tenant every 30 s on every API replica. Whether that scales depends on the expected tenant count; there is no measured problem.
- **Full test suite.** I did not run it. Only targeted probes were run, and the OpenAPI equality check passed.
