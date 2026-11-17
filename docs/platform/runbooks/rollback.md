# Rollback runbook (OPS-04)

Applies to the Supabase + Fly.io pilot (ADR-0017). **A human runs every command here**;
a Claude Code session never touches Fly, Supabase or AWS (CLAUDE.md rule 6). `<APP>` is the
Fly app name from `deploy/supabase/fly.toml`.

## Decide first

| Symptom after a deploy | Action |
| --- | --- |
| `/readyz` failing, 5xx spike, crash loop | Roll back the release (below) |
| Release aborted at `release_command` (migration failed) | Nothing to roll back: the old machines keep serving. Fix forward, see "Migration failed" |
| Data wrong or lost | Stop, do not roll back blindly; see `backup-restore-dr.md` |

## Roll back the application

```bash
fly releases --app <APP>                       # find the last good version, e.g. v41
fly releases rollback 41 --app <APP>           # redeploy that release's image
curl -s https://<APP>.fly.dev/readyz           # must return 200
```

Then run the smoke workflow (`.github/workflows/smoke.yml`, manual) against the URL.
A rollback re-deploys the old image **without** running the old migrations backwards.

## Why the schema must allow it

The previous image runs against the already-migrated schema. This holds only when the
expand/contract policy was followed (`packages/py/db-migrations/README.md`): the last
migration must be an expand step that the previous release tolerates. If the failed release
included a contract step (drop/rename), the previous image may break: restore from backup
instead (`backup-restore-dr.md`). Do **not** run `bomagent-migrate downgrade` on production
unless the revision's docstring says it is lossless.

## Migration failed in `release_command`

Fly keeps the old release serving. Read `fly logs --app <APP>`, fix the revision in a new PR
(never edit an applied revision), redeploy. If the migration half-applied, check
`alembic_version` and the affected schema before retrying.

## Downtime on deploy (note for the owner)

With `--ha=false` (one machine) a deploy replaces the only machine, so there is a short
outage. The audit recommends two `web` machines and the rolling strategy after ARCH-02.
That setting lives in `deploy/supabase/*` (owner's change): `fly scale count 2` and
`strategy = "rolling"` under `[deploy]`. Not changed here.
