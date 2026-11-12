# Supabase pilot deployment (secondary to AWS)

A lightweight second deployment variant next to the AWS one (which stays primary and
unchanged). Everything runs in the EU:

| Concern | Supabase pilot | AWS (primary) |
|---|---|---|
| PostgreSQL + pgvector | Supabase project, region `eu-central-1` (Frankfurt), **own database `bomagent`** | Aurora |
| Auth | Supabase Auth (e-mail + password), access tokens verified against the project's JWKS | Cognito |
| Files | Supabase Storage through its S3-compatible endpoint | S3 |
| Queues | `PostgresQueue` (`app.queue_messages`, migration 0013) | SQS |
| Compute | **one container** (`deploy/docker/allinone.Dockerfile`, package `services/all-in-one`): API + ingest/agent/KB workers + SPA, on an EU container host; config for Fly.io region `fra` in `fly.toml` | ECS Fargate services |
| LLM | deterministic fake provider by default; a real EU provider only through the existing LLM gateway settings | LLM gateway |

The image is host-agnostic: it only reads environment variables and listens on
`BOMAGENT_PORT` (8000). Health: `GET /healthz` (liveness), `GET /readyz` (database and
all queue consumers).

## Image and commands

```bash
docker build -f deploy/docker/allinone.Dockerfile -t bomagent-allinone .   # repo root
```

| Command | Role / credentials | What |
|---|---|---|
| `python -m bomagent_allinone serve` (default `CMD`) | app + platform roles | API, workers, SPA |
| `python -m bomagent_allinone migrate` | migrator (`BOMAGENT_MIGRATOR_DATABASE_URL`) | `bomagent-migrate upgrade`: Alembic to head, then (Supabase only) revokes our database/schemas from `anon`/`authenticated`/`service_role` and CONNECT/TEMPORARY/`public` USAGE from PUBLIC. Fly runs it as `release_command` before each release |
| `python -m bomagent_allinone bootstrap` | Supabase `postgres` role (`BOMAGENT_ADMIN_DATABASE_URL`) | `bomagent-migrate bootstrap`: creates the roles `bomagent_migrator`, `bomagent_app`, `bomagent_platform` (no BYPASSRLS) with their passwords, creates the database `BOMAGENT_DATABASE_NAME` (`bomagent`) when missing, installs pgvector, hands the database to the migrator, grants CONNECT to the runtime roles. Idempotent. Run once (and to rotate role passwords) from an operator machine, **not** on the container host: the admin password is not a runtime secret |

`bootstrap` refuses to prepare `postgres`/`template0`/`template1`: the platform never
takes ownership of Supabase's own `postgres` database (which Supabase's Data API exposes).
Supabase's `postgres` role is not a superuser (CREATEROLE + CREATEDB) - the same
situation as the Aurora master user; the preparation is tested for such a role.

## Environment variables

Names only - values are project-specific. **Secret** = set with `fly secrets set NAME=...`
(or the host's secret store), never in `fly.toml`, the image or git.

### Runtime (serve)

| Variable | Secret | Notes |
|---|---|---|
| `BOMAGENT_ENVIRONMENT` | no | `dev` (or `staging`/`prod`); never `local`/`test` (they enable the mock IdP) |
| `BOMAGENT_PORT`, `BOMAGENT_HOST` | no | default `8000`, `0.0.0.0` |
| `BOMAGENT_LOG_LEVEL`, `BOMAGENT_LOG_JSON` | no | |
| `BOMAGENT_DATABASE_HOST` | no | Supavisor host, e.g. `aws-0-eu-central-1.pooler.supabase.com` (see below) |
| `BOMAGENT_DATABASE_PORT` | no | `5432` (session mode) |
| `BOMAGENT_DATABASE_NAME` | no | `bomagent` |
| `BOMAGENT_DATABASE_USER` | no | `bomagent_app.<project-ref>` behind Supavisor, `bomagent_app` on a direct connection |
| `BOMAGENT_DATABASE_PASSWORD` | **yes** | app role (`bomagent_app`) |
| `BOMAGENT_PLATFORM_DATABASE_USER` | no | `bomagent_platform.<project-ref>` behind Supavisor |
| `BOMAGENT_PLATFORM_DATABASE_PASSWORD` | **yes** | platform role: consumes the queues, onboarding, maintenance |
| `BOMAGENT_DATABASE_URL`, `BOMAGENT_PLATFORM_DATABASE_URL` | **yes** | alternative to the parts above (full URLs, `postgresql+psycopg://...?sslmode=require`) |
| `BOMAGENT_DB_SSL_ROOT_CERT` | no | optional CA file (mounted) for `sslmode=verify-full`; unset = `sslmode=require` |
| `BOMAGENT_DB_POOL_SIZE` | no | app-role pool (default 5, +5 overflow); the platform role uses 2 (+2) |
| `BOMAGENT_QUEUE_BACKEND` | no | `postgres` (the only value the all-in-one accepts; also the default) |
| `BOMAGENT_QUEUE_WAIT_SECONDS`, `BOMAGENT_QUEUE_POLL_INTERVAL_S` | no | long-poll window (5 s) and re-query interval (1 s) |
| `BOMAGENT_DEAD_LETTER_RETENTION_S` | no | dead queue rows are deleted after 14 days |
| `BOMAGENT_SUPABASE_URL` | no | `https://<project-ref>.supabase.co`; issuer and JWKS URL are derived from it |
| `BOMAGENT_SUPABASE_ANON_KEY` | no | anon / publishable key, served to the SPA in `/config.json` (public by design) |
| `BOMAGENT_SOCIAL_PROVIDERS` | no | comma-separated social sign-in buttons served in `/config.json`: `google`, `azure` (Microsoft), `apple`; default empty = none. Set only after the provider is configured in Supabase (`docs/platform/runbooks/social-login.md`) |
| `BOMAGENT_AUTH_MODE` | no | `oidc` (default) |
| `BOMAGENT_OIDC_ISSUER`, `BOMAGENT_OIDC_JWKS_URL` | no | default `<supabase-url>/auth/v1`, `<supabase-url>/auth/v1/.well-known/jwks.json` |
| `BOMAGENT_OIDC_AUDIENCE` | no | default `authenticated` |
| `BOMAGENT_OIDC_ALGORITHMS` | no | JSON list, default `["ES256","RS256"]`; HS* is refused |
| `BOMAGENT_OIDC_EMAIL_CLAIM` | no | default `email` |
| `BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM` | no | default `user_metadata.email_verified` (see "Auth") |
| `BOMAGENT_OIDC_USERINFO_URL`, `BOMAGENT_OIDC_USERINFO_APIKEY` | no | default `<supabase-url>/auth/v1/user` and the anon key: confirms the e-mail with Supabase (see "Auth") |
| `BOMAGENT_OIDC_NAME_CLAIMS` | no | JSON list, default `["user_metadata.full_name","user_metadata.name"]` |
| `BOMAGENT_S3_ENDPOINT_URL` | no | `https://<project-ref>.supabase.co/storage/v1/s3` |
| `BOMAGENT_S3_REGION` | no | the project's region (`eu-central-1`) |
| `BOMAGENT_S3_FORCE_PATH_STYLE` | no | `true` |
| `BOMAGENT_FILES_BUCKET` | no | a **private** Storage bucket, e.g. `bomagent-files` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | **yes** | the Supabase Storage **S3 access keys** (standard AWS SDK variable names) |
| `BOMAGENT_AWS_REGION` | no | `eu-central-1` (unused without AWS services) |
| `BOMAGENT_LLM_GATEWAY_URL` | no | unset = fake provider; set (with the key) only for an EU gateway endpoint (ADR-0006) |
| `BOMAGENT_LLM_GATEWAY_KEY` | **yes** | gateway virtual key |
| `BOMAGENT_EMBEDDING_MODEL` | no | gateway embedding model id (default `fake-embedding`) |
| `BOMAGENT_STATIC_DIR` | no | set by the image (`/app/web`) |
| `BOMAGENT_MAINTENANCE_INTERVAL_S`, `BOMAGENT_RUN_TIMEOUT_S` | no | outbox relay / stuck-run reaper (30 s, 3600 s) |
| `BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT` | no | optional, EU collector only |
| `FORWARDED_ALLOW_IPS` | no | uvicorn: trusted proxies for `X-Forwarded-*` (`*` on Fly, whose proxy is the only route to the port). The client IP it yields is the leftmost `X-Forwarded-For` entry, which a client can set: nothing relies on it today; use Fly's `Fly-Client-IP` for any future IP-based rule |

### Migrations (`migrate`, Fly `release_command`)

| Variable | Secret | Notes |
|---|---|---|
| `BOMAGENT_MIGRATOR_DATABASE_URL` | **yes** | `postgresql+psycopg://bomagent_migrator.<project-ref>:<url-encoded password>@<pooler host>:5432/bomagent?sslmode=require` |

### Preparation (`bootstrap`, operator machine only)

| Variable | Secret | Notes |
|---|---|---|
| `BOMAGENT_ADMIN_DATABASE_URL` | **yes** | the `postgres` role, database **`postgres`** (maintenance connection) |
| `BOMAGENT_DATABASE_NAME` | no | `bomagent` - created and prepared |
| `BOMAGENT_MIGRATOR_PASSWORD`, `BOMAGENT_APP_PASSWORD`, `BOMAGENT_PLATFORM_PASSWORD` | **yes** | role passwords (only the ones present are (re)set) |

## Connection strings

- **Supavisor session mode, port 5432**, supports IPv4 (Fly machines and most hosts);
  the direct host `db.<project-ref>.supabase.co` is IPv6-only unless the IPv4 add-on is
  enabled. Transaction mode (6543) is not used: session settings and prepared statements
  of psycopg/SQLAlchemy need session mode.
- Behind Supavisor the login name is **`<role>.<project-ref>`** for every role -
  `bomagent_app.<ref>`, `bomagent_platform.<ref>`, `bomagent_migrator.<ref>`,
  `postgres.<ref>`. The database name is **`bomagent`** for runtime and migrations,
  `postgres` only for `bootstrap`.
- TLS: composed URLs use `sslmode=require`; for `verify-full` mount the project's CA
  certificate (dashboard, Database settings) and set `BOMAGENT_DB_SSL_ROOT_CERT`.
- Connections per process: app role up to 10, platform role up to 4 (+1 during
  `migrate`); keep them within the pooler's pool size of the plan.

## Auth (Supabase project settings)

- E-mail + password sign-in with **"Confirm email" on**: Supabase then issues tokens only
  after the address was confirmed.
- **Asymmetric JWT signing keys** (ES256 or RS256) must be active: the API verifies
  tokens only against the public JWKS. Tokens signed with the legacy shared JWT secret
  (HS256) are rejected by design.
- `user_metadata` is writable by the signed-in user, so the API does not trust
  `user_metadata.email_verified` where it matters: organisation creation and invitation
  acceptance ask Supabase Auth (`GET <supabase-url>/auth/v1/user` with the caller's token and
  the anon key, `BOMAGENT_OIDC_USERINFO_URL`/`_APIKEY`, derived from `BOMAGENT_SUPABASE_URL`)
  for `email_confirmed_at` and the same address; an unreachable endpoint fails closed.
- Sessions: in Authentication -> Sessions keep **refresh token reuse detection** on and set a
  time-box / inactivity timeout (the SPA keeps the refresh token in `sessionStorage`).
- Roles and organisations still come from **our** database (memberships), never from the
  token; the anon key grants nothing in our database.

## Storage and data isolation

- One **private** bucket and **no policies on `storage.objects`** for it (check Storage ->
  Policies): the application reaches it only with the S3 keys; a policy would let any
  signed-in Supabase user read files with their own token.
- One private bucket; objects are stored under `tenants/{tenant_id}/...` and the
  application refuses keys outside the active tenant's prefix. The S3 access keys have
  full access to the project's storage (they bypass Storage policies): treat them like
  database passwords.
- All tenant data stays under PostgreSQL RLS in `bomagent` (app role without BYPASSRLS);
  the queue table is insert-only for the app role and consumed by the platform role
  through explicit policies (migration 0013).
- The Data API (PostgREST) serves only Supabase's `postgres` database; `migrate`
  additionally revokes everything on `bomagent` from its roles. Disabling the Data API
  in the project is recommended when nothing else uses it.

## Fly.io

`fly.toml` (from the repository root):
`fly deploy . --config deploy/supabase/fly.toml --dockerfile deploy/docker/allinone.Dockerfile --ha=false`
(`--ha=false`: one machine; several machines would also be safe - the queues use
`FOR UPDATE SKIP LOCKED` - but the pilot runs one). Machines never auto-stop (the workers
live in the process); the HTTP check uses `/readyz`; `release_command` runs `migrate`.
Set the project-specific non-secret values in `[env]` and the secrets with
`fly secrets set` before the first deploy.

## Assumptions to verify on the first deployment

Not testable without a real Supabase project (everything else is tested locally against
PostgreSQL 16 + pgvector):

- Supavisor session mode accepts custom roles (`<role>.<ref>`) and a database other than
  `postgres` (`bomagent`); otherwise use the direct connection (IPv6 or IPv4 add-on).
- Supabase's `postgres` role may `CREATE DATABASE`, create the three roles, and install
  pgvector in `bomagent` (`bootstrap` stops with a clear error if not).
- The JWKS endpoint is reachable without an API key and publishes the active signing key
  with `kid`; the access-token claims match the defaults above.
- Supabase Storage's S3 endpoint accepts the client configuration (SigV4, path style,
  region, checksums only when required) for put/get/delete.
- Fly: the build context and `--dockerfile` with `--config` in a subdirectory, and
  `release_command` with the image's `CMD` replaced.

## Security notes (review of 2026-11-12)

- Endpoints that leave the host must use `https://` outside `local`/`test` (Supabase URL,
  JWKS, user endpoint, S3 endpoint, LLM gateway): the settings refuse plain HTTP.
- The parse sandbox limits memory/CPU/time and strips the environment, but on Fly it shares
  the machine's network (in AWS the parsers run in isolated subnets without a route out). A
  parser exploited by a hostile file could send data out - accepted for the pilot with test
  data only (ADR-0017, DECISIONS_LOG); network namespaces for the child are the next step.
- The queue table refuses a message whose envelope names another tenant than its row.
