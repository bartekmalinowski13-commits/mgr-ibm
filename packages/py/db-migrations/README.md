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
- CLI: `bomagent-migrate upgrade|downgrade|bootstrap` (env `BOMAGENT_MIGRATOR_DATABASE_URL`)

## Adding a tenant table

Use `bomagent_migrations.rls.tenant_table_rls("schema.table")` and add isolation tests in
`tests/isolation/`. The catalogue test `test_every_tenant_table_has_forced_rls` fails if a
table with `tenant_id` lacks forced RLS.

## Testing

`uv run pytest tests/isolation packages/py/platform-common -m integration`
(needs PostgreSQL+pgvector, see `packages/py/testing/README.md`).
