"""Organisation API keys for integrations (ARCHITECTURE §5, ADR-0005).

A key belongs to one tenant and carries a role scope (never owner/admin: keys do not
manage members or keys). Only the SHA-256 of the secret is stored. Authenticating a
request is a lookup without tenant context; it stays inside RLS: with
``app.api_key_hash`` set, the ``api_key_lookup`` policy exposes exactly the one active
key with that hash - nothing else.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE tenancy.api_keys (
        id           uuid PRIMARY KEY,
        tenant_id    uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        name         text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
        prefix       text NOT NULL CHECK (length(prefix) BETWEEN 8 AND 16),
        key_hash     text NOT NULL UNIQUE CHECK (key_hash ~ '^[0-9a-f]{64}$'),
        roles        text[] NOT NULL CHECK (roles <@ ARRAY['engineer','reviewer','viewer']::text[]
                                            AND cardinality(roles) > 0),
        created_by   text NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now(),
        expires_at   timestamptz,
        last_used_at timestamptz,
        revoked_at   timestamptz,
        replaced_by  uuid REFERENCES tenancy.api_keys (id)
    )
    """,
    "CREATE INDEX api_keys_tenant ON tenancy.api_keys (tenant_id, created_at DESC, id)",
    """
    CREATE FUNCTION app.current_api_key_hash() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(current_setting('app.api_key_hash', true), '')
    $$
    """,
    "GRANT EXECUTE ON FUNCTION app.current_api_key_hash() TO bomagent_app",
    "GRANT SELECT, INSERT ON tenancy.api_keys TO bomagent_app",
    "GRANT UPDATE (last_used_at, revoked_at, replaced_by) ON tenancy.api_keys TO bomagent_app",
    *tenant_table_rls("tenancy.api_keys"),
    """CREATE POLICY api_key_lookup ON tenancy.api_keys FOR SELECT TO bomagent_app
         USING (key_hash = app.current_api_key_hash() AND revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at > now()))""",
]

DOWNGRADE = [
    "DROP TABLE tenancy.api_keys",
    "DROP FUNCTION app.current_api_key_hash()",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
