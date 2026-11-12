"""Member invitations (M4): an admin invites an e-mail address with roles.

The invitee is not a member yet, so accepting is a cross-tenant lookup. It stays inside
RLS: with ``app.user_email`` (verified e-mail from the token) and ``app.invite_token_hash``
(SHA-256 of the secret the invitee received) set, the ``invitee_lookup`` policy exposes
exactly the one pending, unexpired invitation that matches both - knowing the e-mail
alone or the token alone reveals nothing. Only the hash of the token is stored.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ROLES_CHECK = """roles <@ ARRAY['owner','admin','engineer','reviewer','viewer']::text[]
                 AND cardinality(roles) > 0"""

UPGRADE = [
    f"""
    CREATE TABLE tenancy.invitations (
        id          uuid PRIMARY KEY,
        tenant_id   uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        email       text NOT NULL CHECK (email = lower(email) AND position('@' in email) > 1),
        roles       text[] NOT NULL CHECK ({ROLES_CHECK}),
        token_hash  text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{{64}}$'),
        status      text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'revoked')),
        invited_by  text NOT NULL,
        accepted_by text,
        created_at  timestamptz NOT NULL DEFAULT now(),
        expires_at  timestamptz NOT NULL,
        accepted_at timestamptz
    )
    """,
    "CREATE INDEX invitations_tenant ON tenancy.invitations (tenant_id, created_at DESC, id)",
    """CREATE UNIQUE INDEX invitations_one_pending ON tenancy.invitations (tenant_id, email)
         WHERE status = 'pending'""",
    """
    CREATE FUNCTION app.current_user_email() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(lower(current_setting('app.user_email', true)), '')
    $$
    """,
    """
    CREATE FUNCTION app.current_invite_token_hash() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(current_setting('app.invite_token_hash', true), '')
    $$
    """,
    "GRANT EXECUTE ON FUNCTION app.current_user_email() TO bomagent_app",
    "GRANT EXECUTE ON FUNCTION app.current_invite_token_hash() TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE ON tenancy.invitations TO bomagent_app",
    *tenant_table_rls("tenancy.invitations"),
    """CREATE POLICY invitee_lookup ON tenancy.invitations FOR SELECT TO bomagent_app
         USING (status = 'pending' AND expires_at > now()
                AND email = app.current_user_email()
                AND token_hash = app.current_invite_token_hash())""",
]

DOWNGRADE = [
    "DROP TABLE tenancy.invitations",
    "DROP FUNCTION app.current_invite_token_hash()",
    "DROP FUNCTION app.current_user_email()",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
