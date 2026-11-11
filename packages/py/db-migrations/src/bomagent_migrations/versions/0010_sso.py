"""Single sign-on per organisation (ADR-0005): connection + verified e-mail domains.

* ``tenancy.sso_connections`` - one SAML 2.0 or OIDC identity provider per organisation,
  federated in Cognito under ``provider_name``; ``default_role`` for members created on
  their first SSO sign-in; ``enforce`` - members from the verified domains must use SSO.
  No IdP client secret is stored here (it goes to the identity provider only).
* ``tenancy.sso_domains`` - e-mail domains the organisation proved it controls (DNS TXT
  record with ``token``). A verified domain belongs to one organisation only.

Two lookups run before any tenant context exists and stay inside RLS, like API keys:
with ``app.sso_domain`` set, ``sso_domain_lookup`` shows that one verified domain and
``sso_connection_by_domain`` its organisation's active connection (login discovery);
with ``app.sso_provider`` set, ``sso_connection_by_provider`` shows the connection a
federated user signed in through (membership on first sign-in).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE tenancy.sso_connections (
        tenant_id      uuid PRIMARY KEY REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        protocol       text NOT NULL CHECK (protocol IN ('saml', 'oidc')),
        provider_name  text NOT NULL UNIQUE CHECK (provider_name ~ '^[A-Za-z0-9_-]{3,32}$'),
        metadata_url   text CHECK (metadata_url ~ '^https://'),
        oidc_issuer    text CHECK (oidc_issuer ~ '^https://'),
        oidc_client_id text,
        default_role   text NOT NULL DEFAULT 'viewer'
                       CHECK (default_role IN ('engineer', 'reviewer', 'viewer')),
        enforce        boolean NOT NULL DEFAULT false,
        status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'failed')),
        error          text,
        created_by     text NOT NULL,
        updated_at     timestamptz NOT NULL DEFAULT now(),
        CHECK (protocol <> 'saml' OR metadata_url IS NOT NULL),
        CHECK (protocol <> 'oidc' OR (oidc_issuer IS NOT NULL AND oidc_client_id IS NOT NULL))
    )
    """,
    """
    CREATE TABLE tenancy.sso_domains (
        tenant_id   uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        domain      text NOT NULL CHECK (domain ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'),
        token       text NOT NULL CHECK (length(token) >= 32),
        verified_at timestamptz,
        created_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, domain)
    )
    """,
    # a verified domain belongs to exactly one organisation
    """CREATE UNIQUE INDEX sso_domains_verified ON tenancy.sso_domains (domain)
         WHERE verified_at IS NOT NULL""",
    """
    CREATE FUNCTION app.current_sso_domain() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(lower(current_setting('app.sso_domain', true)), '')
    $$
    """,
    """
    CREATE FUNCTION app.current_sso_provider() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(current_setting('app.sso_provider', true), '')
    $$
    """,
    "GRANT EXECUTE ON FUNCTION app.current_sso_domain() TO bomagent_app",
    "GRANT EXECUTE ON FUNCTION app.current_sso_provider() TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenancy.sso_connections TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenancy.sso_domains TO bomagent_app",
    *tenant_table_rls("tenancy.sso_connections"),
    *tenant_table_rls("tenancy.sso_domains"),
    """CREATE POLICY sso_domain_lookup ON tenancy.sso_domains FOR SELECT TO bomagent_app
         USING (domain = app.current_sso_domain() AND verified_at IS NOT NULL)""",
    """CREATE POLICY sso_connection_by_domain ON tenancy.sso_connections FOR SELECT
         TO bomagent_app
         USING (status = 'active' AND tenant_id IN (
                  SELECT d.tenant_id FROM tenancy.sso_domains d
                  WHERE d.domain = app.current_sso_domain() AND d.verified_at IS NOT NULL))""",
    """CREATE POLICY sso_connection_by_provider ON tenancy.sso_connections FOR SELECT
         TO bomagent_app
         USING (status = 'active' AND provider_name = app.current_sso_provider())""",
]

DOWNGRADE = [
    "DROP TABLE tenancy.sso_domains",
    "DROP TABLE tenancy.sso_connections",
    "DROP FUNCTION app.current_sso_provider()",
    "DROP FUNCTION app.current_sso_domain()",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
