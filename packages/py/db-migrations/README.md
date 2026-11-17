# bomagent-db-migrations

**Responsibility:** the PostgreSQL schema of the whole platform (one database, schemas per
module: `app`, `tenancy`, `audit`, `kb`, `projects`, `runs`, `bom`, ...), cluster roles and
Row-Level Security policies.

## Why one migrations package

All services share one Aurora cluster (ADR-0004). Domain packages define their tables as
SQLAlchemy Core objects for queries, but DDL lives here as **hand-written** Alembic
migrations, because every tenant table needs explicit, reviewed RLS policies
(`SECURITY.md`: every migration changing RLS is security-reviewed).

## Roles (`bootstrap.sql`)

| Role                | Purpose                                         | BYPASSRLS |
| ------------------- | ----------------------------------------------- | --------- |
| `bomagent_migrator` | owns objects, runs migrations (separate secret) | no        |
| `bomagent_app`      | API and workers                                 | **no**    |
| `bomagent_platform` | platform pipelines (global KB, onboarding)      | **no**    |

Tables are `ENABLE` + `FORCE ROW LEVEL SECURITY`; policies compare with
`app.current_tenant_id()` (from `set_config('app.tenant_id', ..., true)`), which is NULL
without context, so "no context" means "no rows".

## Public interface

- `bomagent_migrations.bootstrap(admin_url, passwords)` - create roles (idempotent)
- `bomagent_migrations.upgrade(url, revision="head")`, `downgrade(url, revision)`
- `bomagent_migrations.prepare_database(admin_url, passwords, database=None)` - as the
  cluster administrator (Aurora master user or Supabase's `postgres` role: CREATEROLE +
  CREATEDB, not a superuser): roles + passwords, creates `database` when it differs from
  the one `admin_url` points at (Supabase: connect to `postgres`, prepare `bomagent`),
  pgvector (a clear `RuntimeError` when the administrator may not install it), database
  owned by the migrator, CONNECT for the runtime roles. Refuses `postgres`/`template0`/
  `template1` (the platform never takes over a system database). Idempotent; used by the
  AWS `dbbootstrap` task, the Supabase pilot and the test fixtures.
- `bomagent_migrations.upgrade(url)` runs Alembic and then `revoke_data_api_roles(url)`:
  **only when** Supabase's Data API roles (`anon`, `authenticated`, `service_role`) exist,
  they lose every privilege on our database and schemas, CONNECT/TEMPORARY on the database
  and USAGE on `public` are revoked from PUBLIC (the runtime roles get explicit grants).
  A no-op on plain PostgreSQL and Aurora.
- CLI: `bomagent-migrate upgrade|downgrade` (env `BOMAGENT_MIGRATOR_DATABASE_URL`);
  `bomagent-migrate bootstrap` (env `BOMAGENT_ADMIN_DATABASE_URL` or
  `BOMAGENT_ADMIN_USER`/`BOMAGENT_ADMIN_PASSWORD`/`BOMAGENT_DATABASE_HOST`, passwords from
  `BOMAGENT_{MIGRATOR,APP,PLATFORM}_PASSWORD`; `BOMAGENT_DATABASE_NAME` names the database
  to prepare, created when missing)

## Platform-role exceptions

Since 0015 (SEC-15) the platform role can no longer insert into `tenancy.tenants` or touch
`tenancy.memberships` at all: onboarding goes through the `SECURITY DEFINER` function
`tenancy.create_organization(...)` (owned by the migrator, `search_path` pinned, EXECUTE only
for `bomagent_platform`), which creates a tenant and its first owner atomically. The owner is
subject to `FORCE ROW LEVEL SECURITY`, so the migrator has the narrow INSERT-only policies
`migrator_create_organization`; nobody connects as the migrator at run time. The platform role
keeps `platform_tenants_read` / `platform_tenants_update` on `tenancy.tenants` (maintenance
lists tenants, plan changes). Test helpers seed tenants through the migrator, never the
platform role (`bomagent_testing.fixtures.create_tenant`).

The platform role sees other tenant rows only through explicit, named policies:
`platform_tenants_read`/`platform_tenants_update` (`tenancy.tenants`), `kb_global_write`
(global corpus only) and, since 0013, `queue_consumer_*` on `app.queue_messages` (the
PostgreSQL queue of the Supabase pilot): SELECT/DELETE and UPDATE of the delivery columns
only (`visible_at`, `receive_count`, `receipt`, `dead_at`), no INSERT. The app role may
only INSERT queue rows of its own tenant (no SELECT). Rationale in the migration docstring.

## Adding a tenant table

Use `bomagent_migrations.rls.tenant_table_rls("schema.table")` and add isolation tests in
`tests/isolation/`. The catalogue test `test_every_tenant_table_has_forced_rls` fails if a
table with `tenant_id` lacks forced RLS.

## Expand/contract policy (OPS-04)

A release must be safe to roll back to the previous image (see
`docs/platform/runbooks/rollback.md`), and during a rolling deploy two app versions run
against one schema. Therefore every schema change that removes or reshapes something is
split over **at least two releases**:

1. **Expand** (release N): add the new column/table/index (nullable or with a `DEFAULT`),
   deploy code that writes both old and new and reads the new with a fallback. Backfill in
   batches, never in one locking statement.
2. **Migrate**: verify in production that nothing reads or writes the old shape.
3. **Contract** (release N+1 or later): a revision that only drops the old column/table
   (or sets `NOT NULL`, changes a type, renames). No code of the previous release may
   depend on what it removes, because rolling back one release must still work.

Rules enforced by `tools/migration_lint.py` (part of `just lint`/CI):

- `DROP COLUMN`, `DROP TABLE` of an existing table, `RENAME`, `SET NOT NULL`,
  `ALTER COLUMN ... TYPE` fail the lint unless recorded in `BASELINE` with a reason
  (reviewed; for a deliberate contract step).
- `contract-mixed`: a revision containing a `DROP COLUMN`/`DROP TABLE` must contain nothing
  else, so a contract step never ships in the same release as the expand it depends on.
- Every revision keeps a real `downgrade()`; a contract step's downgrade re-creates the
  structure (data loss is documented in the revision docstring).

Reviewers check these in the PR; the migration runs as Fly's `release_command` before the
new machines take traffic, so a failing migration aborts the release.

## Indexes on live tables

Build indexes on existing tables `CONCURRENTLY` inside `op.get_context().autocommit_block()`
(see `0016`): no write lock, but not allowed in a transaction block. Drop a leftover INVALID
index of the same name first (`DROP INDEX CONCURRENTLY IF EXISTS`), then create it. The
migration lint reports `index-on-existing-table`; record it in `tools/migration_lint.py`
`BASELINE` with the reason ("CONCURRENTLY"). Small tables created in the same revision need
neither.

## Growth and retention (DATA-01)

| Table | Growth | Bound |
|---|---|---|
| `app.idempotency_keys` | one row per idempotent request | 24 h TTL, maintenance sweep (`expire_idempotency_keys`) |
| `app.rate_windows` | one row per subject and minute (UNLOGGED) | own subject cleaned on first hit of a window; 1 h TTL sweep for the rest (`expire_rate_windows`) |
| `app.outbox` | one row per event | `sent` rows purged by the sweep (`cleanup_sent`); `dead` rows kept for ops (OPS-03) |
| `app.queue_messages` | one row per message (pilot queue) | consumed rows are deleted; `dead_at` rows kept for ops (OPS-03), alert on count |
| `runs.graph_checkpoints/graph_writes` | per step of a running graph | deleted when the run ends; cascade with the run |
| `audit.events` | append-only | never deleted (hash chain); archived by anchors |
| `runs.runs.trace` | one JSON element per graph step, rewritten by `trace = trace \|\| ...` | see below |
| `bom.versions.content` | one immutable version per edit | by plan quota (not enforced yet) |

`runs.runs.trace`: the complete trace is written to the object store (`trace.json`) when the
run ends, so the database copy is a convenience for the run page and the SSE stream. Approach
for the cap (not implemented, needs a product decision because the run page reads this copy):
(1) keep at most the last N steps (e.g. 200) in the row for running runs and replace the
column by a pointer to `trace.json` after the run has been terminal for 30 days (a contract
step, two releases); (2) until then the growth is bounded by the graph's step budget
(`Budget` in the agent runtime), i.e. by plan limits, not by user input.

## Testing

`uv run pytest tests/isolation packages/py/platform-common -m integration`
(needs PostgreSQL+pgvector, see `packages/py/testing/README.md`).
