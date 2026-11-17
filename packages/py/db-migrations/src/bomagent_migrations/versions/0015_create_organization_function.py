"""Onboarding through one narrow SECURITY DEFINER function (audit SEC-15).

Before this revision the platform role (``bomagent_platform``), which the API process holds
for onboarding, maintenance and queue consumption, could ``INSERT`` any row into
``tenancy.tenants`` and ``tenancy.memberships`` (policies ``platform_onboarding`` with
``USING (true) WITH CHECK (true)``). Threat model: an RCE or SSRF-to-SQL in the API could
insert an ``owner`` membership into *any* tenant and then read or change all of its data
through the normal application path.

After this revision:

* ``tenancy.create_organization(id, slug, name, owner_sub, email, display_name)`` creates a
  tenant and its first ``owner`` membership atomically and does nothing else. The tenant id
  is the primary key of ``tenancy.tenants``, so the function can never attach an owner to an
  existing tenant (the first INSERT fails with a unique violation, the transaction rolls
  back); the slug stays unique as before (callers map the violation to 409).
* The function is ``SECURITY DEFINER``, owned by ``bomagent_migrator`` (not a superuser, no
  ``BYPASSRLS``), with ``search_path = pg_catalog, pg_temp`` and every object schema-qualified
  (no search-path hijacking through ``pg_temp`` or a writable schema). ``EXECUTE`` is revoked
  from ``PUBLIC`` and granted to ``bomagent_platform`` only (the API's onboarding connection);
  the application role cannot call it.
* The tables are ``FORCE ROW LEVEL SECURITY``, which applies to the owner too, so the
  definer needs policies. They are narrow and named: ``migrator_create_organization`` allows
  the migrator to INSERT a tenant row whose id equals ``app.tenant_id`` and a membership
  with exactly ``ARRAY['owner']`` in that same tenant, nothing else (no SELECT, UPDATE or
  DELETE). The function sets ``app.tenant_id`` transaction-locally to the new id for the
  duration of the two INSERTs and restores the caller's previous value afterwards. Nobody
  connects as the migrator at run time (its credentials are only used by the release
  command), so these policies are not reachable from the API.
* ``bomagent_platform`` loses ``INSERT`` on both tables and every privilege on
  ``tenancy.memberships``; ``platform_onboarding`` is replaced on ``tenancy.tenants`` by a
  SELECT policy (maintenance lists tenants) and an UPDATE policy (plan changes), and dropped
  on memberships. The platform role can therefore no longer create or alter memberships at
  all, and cannot create tenants except through the function.

Residual risk (documented, not solved here): the platform role can still call the function
and so create *new* tenants with an owner of its choosing; that is the onboarding feature
itself. Separating the onboarding connection from the maintenance/outbox connection (own
minimal roles) is the AWS follow-up of SEC-15 and needs infrastructure changes.

Rollback: ``alembic downgrade 0014`` restores the previous grants and policies exactly and
drops the function (the API of the previous release inserts directly again).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-17
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

FUNCTION_SIGNATURE = "tenancy.create_organization(uuid, text, text, text, text, text)"

UPGRADE = [
    # --- policies the definer (owner) needs under FORCE ROW LEVEL SECURITY
    """CREATE POLICY migrator_create_organization ON tenancy.tenants
         FOR INSERT TO bomagent_migrator
         WITH CHECK (id = app.current_tenant_id())""",
    """CREATE POLICY migrator_create_organization ON tenancy.memberships
         FOR INSERT TO bomagent_migrator
         WITH CHECK (tenant_id = app.current_tenant_id() AND roles = ARRAY['owner']::text[])""",
    """
    CREATE FUNCTION tenancy.create_organization(
        p_id uuid, p_slug text, p_name text, p_owner_sub text, p_email text,
        p_display_name text)
    RETURNS uuid
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_previous text := pg_catalog.current_setting('app.tenant_id', true);
    BEGIN
        IF p_id IS NULL THEN
            RAISE EXCEPTION 'organisation id is required' USING ERRCODE = 'null_value_not_allowed';
        END IF;
        PERFORM pg_catalog.set_config('app.tenant_id', p_id::text, true);
        INSERT INTO tenancy.tenants (id, slug, name) VALUES (p_id, p_slug, p_name);
        INSERT INTO tenancy.memberships (tenant_id, user_sub, email, display_name, roles)
             VALUES (p_id, p_owner_sub, pg_catalog.lower(p_email), COALESCE(p_display_name, ''),
                     ARRAY['owner']::text[]);
        PERFORM pg_catalog.set_config('app.tenant_id', COALESCE(v_previous, ''), true);
        RETURN p_id;
    END
    $$
    """,
    f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO bomagent_platform",
    # --- take the broad platform access away
    "REVOKE INSERT ON tenancy.tenants FROM bomagent_platform",
    "REVOKE ALL ON tenancy.memberships FROM bomagent_platform",
    "DROP POLICY platform_onboarding ON tenancy.tenants",
    "DROP POLICY platform_onboarding ON tenancy.memberships",
    """CREATE POLICY platform_tenants_read ON tenancy.tenants
         FOR SELECT TO bomagent_platform USING (true)""",
    """CREATE POLICY platform_tenants_update ON tenancy.tenants
         FOR UPDATE TO bomagent_platform USING (true) WITH CHECK (true)""",
]

DOWNGRADE = [
    "DROP POLICY platform_tenants_update ON tenancy.tenants",
    "DROP POLICY platform_tenants_read ON tenancy.tenants",
    """CREATE POLICY platform_onboarding ON tenancy.tenants TO bomagent_platform
         USING (true) WITH CHECK (true)""",
    """CREATE POLICY platform_onboarding ON tenancy.memberships TO bomagent_platform
         USING (true) WITH CHECK (true)""",
    "GRANT INSERT ON tenancy.tenants TO bomagent_platform",
    "GRANT SELECT, INSERT ON tenancy.memberships TO bomagent_platform",
    f"DROP FUNCTION {FUNCTION_SIGNATURE}",
    "DROP POLICY migrator_create_organization ON tenancy.memberships",
    "DROP POLICY migrator_create_organization ON tenancy.tenants",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
