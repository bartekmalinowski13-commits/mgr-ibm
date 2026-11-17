# Supabase Custom Access Token hook (audit SEC-07)

**Who:** the owner, by hand, in the Supabase dashboard and SQL editor. Nothing in the platform
(and no Claude Code session) calls Supabase.

**Why:** the API reads `email_verified` from `user_metadata.email_verified` (Supabase pilot,
`BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM`). `user_metadata` is writable by the signed-in user
(`supabase.auth.updateUser({ data: { email_verified: true } })`). The API compensates with a
userinfo check, but the claim itself is forgeable. The hook makes GoTrue put a server-side
`email_verified` (from `auth.users.email_confirmed_at`) at the top level of the access token,
where users cannot write.

**Important:** the function lives in Supabase's own `postgres` database (the one that has the
`auth` schema), **not** in the `bomagent` database that `bomagent-migrate` upgrades. That is why
it is a standalone SQL file and not an Alembic revision:
[`deploy/supabase/sql/001_custom_access_token_hook.sql`](../../../deploy/supabase/sql/001_custom_access_token_hook.sql)
(threat model in its header, tested by `packages/py/db-migrations/tests/test_supabase_hook.py`).

## Enable (once)

1. Dashboard -> **SQL Editor** (project database `postgres`) -> paste the file and run it.
   Idempotent (`CREATE OR REPLACE`). It creates `public.bomagent_custom_access_token_hook(jsonb)`
   and allows only `supabase_auth_admin` to execute it (revoked from PUBLIC, `anon`,
   `authenticated`, `service_role`, so the Data API cannot call it).
2. Dashboard -> **Authentication -> Hooks (Beta) -> Customize Access Token (JWT) Claims hook**
   -> type *Postgres function* -> schema `public`, function `bomagent_custom_access_token_hook`
   -> **Enable**.
3. Sign in once and decode the access token (jwt.io offline or `jq`): the top level must contain
   `"email_verified": true` for a confirmed user. Test an unconfirmed account too: it must be
   `false`.
4. Only now switch the API: `fly secrets set --app <APP> BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM=email_verified`
   (the all-in-one default is still `user_metadata.email_verified`, deliberately unchanged so
   that deploying this code does not break sign-in before the hook exists). Keep the userinfo
   fallback as it is.

## Roll back

1. `fly secrets set ... BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM=user_metadata.email_verified`.
2. Dashboard -> Authentication -> Hooks -> disable the hook (**before** dropping the function:
   with the hook enabled and the function missing every sign-in fails).
3. SQL editor: `DROP FUNCTION IF EXISTS public.bomagent_custom_access_token_hook(jsonb);`
   (the DOWN section of the SQL file).

## Not covered here

Refusing tokens whose `email` differs from the stored membership e-mail outside SSO
enforcement is API code in `auth.py` (separate task).
