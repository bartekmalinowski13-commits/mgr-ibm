# all-in-one (`bomagent_allinone`)

**Responsibility:** the single process of the lightweight **Supabase pilot** deployment
(`deploy/supabase/`). AWS stays the primary deployment with separate services; this
package only composes them.

| Part | How |
|---|---|
| API | `bomagent_api.create_app` unchanged, incl. the maintenance loop (outbox relay, stuck-run reaper) |
| Queues | `PostgresQueue` (`app.queue_messages`, migration 0013) for `ingest`, `runs`, `kb`: the API inserts with the app role, the in-process consumers read with the platform role; handlers run in the message's tenant context with the app role (RLS) |
| Workers | ingest (`IngestWorker`), agent (`RunWorker`), KB indexer (`KbIndexer`) - the same handlers as the AWS services; design files are parsed in the resource-limited sandbox (`bomagent_cad.sandbox`); one message at a time per queue; a dead-letter purge after 14 days |
| SPA | files from `BOMAGENT_STATIC_DIR` (`apps/web/dist`), SPA fallback to `index.html` for non-`/v1` GET paths (a missing file with an extension -> 404), hashed `assets/` cached immutably, `index.html` `no-cache`, CSP `default-src 'self'` with `connect-src` limited to the own origin and the Supabase project |
| `/config.json` | `{"auth":{"mode":"supabase","url":...,"anonKey":...}}` from `BOMAGENT_SUPABASE_URL` / `BOMAGENT_SUPABASE_ANON_KEY` (the anon key is public by design); `{"auth":{"mode":"local"}}` with `BOMAGENT_AUTH_MODE=local` (local/test only); 404 when neither |
| Health | `/healthz` (liveness), `/readyz` (database + all consumer tasks alive) |
| LLM | the EU LLM gateway when `BOMAGENT_LLM_GATEWAY_URL`/`_KEY` are set (existing gateway settings, no new provider code); otherwise the deterministic fake provider (logged as `llm_fake_provider`) |

## Public interface

- `bomagent_allinone.app.Settings` - `bomagent_api.app.Settings` plus `supabase_url`,
  `supabase_anon_key`, `static_dir`, `start_workers`, `db_pool_size`,
  `dead_letter_retention_s`, `use_docling`. Defaults are Supabase's: queue backend
  `postgres` (the only one accepted), OIDC audience `authenticated`, issuer and JWKS
  derived from `supabase_url` (`/auth/v1`, `/auth/v1/.well-known/jwks.json`), algorithms
  `ES256`/`RS256`, `user_metadata.email_verified`, names from `user_metadata.full_name` /
  `user_metadata.name`.
- `bomagent_allinone.app.create_app(settings, *, engine, platform_engine, store, chat, kb,
  retriever_factory)` - injectable for tests.
- `python -m bomagent_allinone [serve|migrate|bootstrap]` - serve (default); `migrate` =
  `bomagent-migrate upgrade`; `bootstrap` = `bomagent-migrate bootstrap`.

Environment variables and secrets: `deploy/supabase/README.md`.

## Testing

```bash
export BOMAGENT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/postgres
uv run pytest services/all-in-one     # in-process: upload a KiCad project, run variant B
```
