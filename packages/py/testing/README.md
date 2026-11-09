# bomagent-testing

Shared pytest plugin (loaded from the root `conftest.py`). Development dependency only.

## Database for integration and isolation tests

1. If `BOMAGENT_TEST_DATABASE_URL` is set (a **superuser** URL, e.g.
   `postgresql+psycopg://postgres:postgres@localhost:5432/postgres`), it is used directly.
2. Otherwise a `pgvector/pgvector:pg16` container is started with Testcontainers (CI).
3. If neither is possible, tests marked `integration`/`isolation` **fail** (they are never
   silently skipped - isolation tests block merges).

A fresh database `bomagent_test_<random>` is created per session, roles are bootstrapped,
migrations run as `bomagent_migrator`, and tests connect as `bomagent_app`
(no `BYPASSRLS`) or `bomagent_platform`.

## Fixtures

| Fixture           | Scope    | What                                                                |
| ----------------- | -------- | ------------------------------------------------------------------- |
| `db_urls`         | session  | URLs for admin / migrator / app / platform roles of the migrated DB |
| `app_engine`      | session  | `AsyncEngine` connected as `bomagent_app`                           |
| `platform_engine` | session  | `AsyncEngine` connected as `bomagent_platform`                      |
| `make_tenant`     | function | async factory creating a tenant, returns `TenantContext`            |
