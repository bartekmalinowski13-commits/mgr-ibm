-- Supabase Custom Access Token hook (audit SEC-07).
--
-- WHERE THIS RUNS: in Supabase's own `postgres` database (the one with the `auth` schema),
-- NOT in the `bomagent` database that Alembic migrates. GoTrue calls the function while it
-- issues a token; it cannot reach another database. The owner applies this file once with
-- the SQL editor or psql as the `postgres` role, then enables the hook in the dashboard
-- (docs/platform/runbooks/supabase-access-token-hook.md). Nothing in the platform calls
-- Supabase, so this file is only ever applied by a human.
--
-- WHAT IT DOES: sets the top-level claim `email_verified` from `auth.users.email_confirmed_at`
-- (server-side truth). Today the API reads `user_metadata.email_verified`, which the user can
-- write with `supabase.auth.updateUser({ data: { email_verified: true } })`; the API
-- mitigates that with a userinfo check. With the hook, the claim cannot be forged: top-level
-- claims are only set by GoTrue and by this function.
--
-- THREAT MODEL: the function runs as `supabase_auth_admin` (the role GoTrue connects with),
-- is NOT security definer, reads exactly one row of `auth.users` by primary key, writes
-- nothing and returns only the event's claims plus `email_verified`. EXECUTE is revoked from
-- PUBLIC, anon, authenticated and service_role so nobody can call it through the Data API
-- (PostgREST) and probe which user ids are confirmed. `search_path` is pinned and every
-- object is schema-qualified. An unknown user id yields `email_verified = false`. The hook
-- never raises: a failing hook would block every login.
--
-- ROLLBACK: run the DOWN section at the bottom (disable the hook in the dashboard first,
-- otherwise logins fail with "hook not found"), then set BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM
-- back to `user_metadata.email_verified`.

-- ---------------------------------------------------------------------------- UP
CREATE OR REPLACE FUNCTION public.bomagent_custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_claims    jsonb := COALESCE(event -> 'claims', '{}'::jsonb);
    v_user_id   uuid;
    v_confirmed boolean := false;
BEGIN
    BEGIN
        v_user_id := (event ->> 'user_id')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        v_user_id := NULL;
    END;
    IF v_user_id IS NOT NULL THEN
        SELECT (u.email_confirmed_at IS NOT NULL) INTO v_confirmed
          FROM auth.users u
         WHERE u.id = v_user_id;
    END IF;
    v_claims := pg_catalog.jsonb_set(
        v_claims, '{email_verified}', pg_catalog.to_jsonb(COALESCE(v_confirmed, false)), true);
    RETURN pg_catalog.jsonb_set(event, '{claims}', v_claims, true);
END
$$;

GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
REVOKE ALL ON FUNCTION public.bomagent_custom_access_token_hook(jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.bomagent_custom_access_token_hook(jsonb) TO supabase_auth_admin;
-- GoTrue reads `auth.users` as supabase_auth_admin (its owner) already; nothing to grant.

-- ---------------------------------------------------------------------------- DOWN
-- DROP FUNCTION IF EXISTS public.bomagent_custom_access_token_hook(jsonb);
