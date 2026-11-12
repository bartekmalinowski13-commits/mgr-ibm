# Runbook: Supabase pilot (second, lightweight variant - ADR-0017)

The quick way to put the app in front of testers: a Supabase project in Frankfurt (database,
sign-in, file storage) + one container on Fly.io in Frankfurt. AWS stays the primary path
(`single-account-dev.md`). All steps are done by the owner; Claude Code never creates cloud
resources (CLAUDE.md §6). Technical reference: `deploy/supabase/README.md`.

**Use it only with non-confidential data** until you have accepted ADR-0017 and checked the
data processing terms (DPA, EU region, sub-processors) of Supabase and Fly.io.

What works: the whole app (projects, uploads, parsing in the sandbox, runs A/B, BOM,
corrections, export, KB, audit log, members, invitations, API keys). What does not: SSO per
organisation, WAF, Bedrock. Without an LLM gateway configured, runs use the deterministic
fake model (good for testing the product flow, not for real BOMs or the thesis experiment).

Placeholders: `<REF>` = Supabase project ref (from its URL), `<APP>` = your Fly app name,
`<POOLER>` = the session pooler host shown in Supabase -> Connect (e.g.
`aws-0-eu-central-1.pooler.supabase.com`).

## 1. Supabase project (dashboard)

1. Create a project, region **Frankfurt (eu-central-1)**. Save the database password in a
   password manager.
2. **Authentication -> Sign In / Providers -> Email:** enabled, **"Confirm email" ON**
   (mandatory: the API trusts the e-mail only because Supabase issues tokens after
   confirmation).
3. **Project Settings -> JWT Keys:** switch to **asymmetric signing keys** (ES256 or RS256)
   and make the new key current. The API refuses tokens signed with the legacy shared secret.
4. **Storage:** create a **private** bucket `bomagent-files` and add **no policies** for it
   (Storage -> Policies must stay empty for this bucket). Storage -> Settings -> S3
   connection: enable, create an access key; save the key id and secret.
5. **Project Settings -> Data API:** disable it if nothing else uses this project.
6. **Authentication -> Sessions:** keep refresh token reuse detection on; set a time-box
   (e.g. 7 days) and an inactivity timeout (e.g. 24 h).
7. Note the project URL `https://<REF>.supabase.co` and the **anon / publishable key**
   (public by design; the web app receives it).

## 2. Prepare the database (once, from your Mac)

Generate three role passwords (letters and digits only):

```bash
for r in MIGRATOR APP PLATFORM; do echo "BOMAGENT_${r}_PASSWORD=$(openssl rand -hex 24)"; done
```

Save them in the password manager, then run (in the repository, after `just bootstrap`):

```bash
BOMAGENT_ADMIN_DATABASE_URL='postgresql+psycopg://postgres.<REF>:<DB PASSWORD>@<POOLER>:5432/postgres?sslmode=require' BOMAGENT_DATABASE_NAME=bomagent BOMAGENT_MIGRATOR_PASSWORD=... BOMAGENT_APP_PASSWORD=... BOMAGENT_PLATFORM_PASSWORD=... uv run python -m bomagent_allinone bootstrap
```

It creates the database `bomagent`, the three roles (no BYPASSRLS) and pgvector. If it
stops with an error, paste it into a Claude Code session.

## 3. Fly.io app (from your Mac)

```bash
brew install flyctl
```

```bash
fly auth signup
```

```bash
fly apps create <APP>
```

In `deploy/supabase/fly.toml` set `app = "<APP>"` and fill the commented `[env]` values
(Supabase URL, anon key, S3 endpoint `https://<REF>.supabase.co/storage/v1/s3`, pooler host,
users `bomagent_app.<REF>` and `bomagent_platform.<REF>`). Then the secrets:

```bash
fly secrets set --app <APP> BOMAGENT_DATABASE_PASSWORD=<APP PASSWORD> BOMAGENT_PLATFORM_DATABASE_PASSWORD=<PLATFORM PASSWORD> BOMAGENT_MIGRATOR_DATABASE_URL='postgresql+psycopg://bomagent_migrator.<REF>:<MIGRATOR PASSWORD>@<POOLER>:5432/bomagent?sslmode=require' AWS_ACCESS_KEY_ID=<STORAGE KEY ID> AWS_SECRET_ACCESS_KEY=<STORAGE SECRET>
```

## 4. Deploy

```bash
fly deploy . --config deploy/supabase/fly.toml --dockerfile deploy/docker/allinone.Dockerfile --ha=false
```

The release step runs the migrations, then the machine starts. Check:

```bash
curl -s https://<APP>.fly.dev/readyz
```

## 5. First sign-in

1. Supabase -> Authentication -> URL Configuration: **Site URL** = `https://<APP>.fly.dev`
   (confirmation and password-reset e-mails link there).
2. Open `https://<APP>.fly.dev`, "Create account", confirm the e-mail, sign in, create the
   organisation - you are its owner. Invite testers from Settings -> Members.
3. Supabase's built-in e-mail sender has a low hourly limit; for more testers configure your
   own SMTP in Supabase (Authentication -> Emails).

## 6. Updates, costs, switching off

- New version: merge to `main`, pull on your Mac, run the deploy command again.
- Costs: Fly bills the running machine (`shared-cpu-2x`, 2 GB, always on); Supabase has a
  free tier with limits and paid plans - check both pricing pages before inviting testers.
- Switch off: `fly scale count 0 --app <APP>` (stops compute); delete the Fly app and the
  Supabase project when the pilot ends.

## What still needs checking on the first deployment

Listed in `deploy/supabase/README.md` ("Assumptions to verify"): custom roles through the
Supavisor pooler, `CREATE DATABASE` for Supabase's `postgres` role, the JWKS endpoint and
token claims, the Storage S3 endpoint with our client settings, Fly build paths. If any step
fails, copy the exact error into a Claude Code session.
