"""Platform core (M4): memberships, projects, files, runs, BOM versions, idempotency.

Every table carries ``tenant_id`` with forced RLS. Users are identified by the OIDC
``sub``; a membership row is the user's identity *inside* one organisation. Finding the
organisations of a user at login is the only cross-tenant lookup: with
``app.user_sub`` set (``user_transaction``) narrow SELECT policies expose exactly that
user's memberships and their tenants - no role bypasses RLS.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10
"""

from alembic import op

from bomagent_migrations.rls import APP_ROLES, tenant_table_rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = [
    "tenancy.memberships",
    "projects.projects",
    "projects.files",
    "runs.runs",
    "bom.versions",
    "app.idempotency_keys",
]

UPGRADE = [
    "CREATE SCHEMA IF NOT EXISTS projects",
    "CREATE SCHEMA IF NOT EXISTS runs",
    "CREATE SCHEMA IF NOT EXISTS bom",
    f"GRANT USAGE ON SCHEMA projects, runs, bom TO {APP_ROLES}",
    """
    CREATE TABLE tenancy.memberships (
        tenant_id    uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        user_sub     text NOT NULL CHECK (length(user_sub) BETWEEN 1 AND 255),
        email        text NOT NULL CHECK (position('@' in email) > 1),
        display_name text NOT NULL DEFAULT '',
        roles        text[] NOT NULL CHECK (roles <@ ARRAY['owner','admin','engineer',
                                                           'reviewer','viewer']::text[]
                                            AND cardinality(roles) > 0),
        status       text NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active')),
        created_at   timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, user_sub)
    )
    """,
    "CREATE INDEX memberships_sub ON tenancy.memberships (user_sub)",
    """
    CREATE TABLE projects.projects (
        id          uuid PRIMARY KEY,
        tenant_id   uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
        description text NOT NULL DEFAULT '' CHECK (length(description) <= 4000),
        created_by  text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX projects_tenant ON projects.projects (tenant_id, created_at DESC, id)",
    """
    CREATE TABLE projects.files (
        id              uuid PRIMARY KEY,
        tenant_id       uuid NOT NULL,
        project_id      uuid NOT NULL REFERENCES projects.projects (id) ON DELETE CASCADE,
        name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 255),
        object_key      text NOT NULL,
        sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        size_bytes      bigint NOT NULL CHECK (size_bytes >= 0),
        status          text NOT NULL DEFAULT 'uploaded'
                        CHECK (status IN ('uploaded', 'parsed', 'failed')),
        detected_format text,
        summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_by      text NOT NULL,
        created_at      timestamptz NOT NULL DEFAULT now(),
        UNIQUE (project_id, name)
    )
    """,
    """
    CREATE TABLE runs.runs (
        id              uuid PRIMARY KEY,
        tenant_id       uuid NOT NULL,
        project_id      uuid NOT NULL REFERENCES projects.projects (id) ON DELETE CASCADE,
        variant         text NOT NULL CHECK (variant IN ('A', 'B')),
        runtime         text NOT NULL,
        model_id        text NOT NULL,
        status          text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'completed', 'failed',
                                          'budget_exceeded')),
        requirements    jsonb NOT NULL DEFAULT '{}'::jsonb,
        kb_snapshot_id  text,
        usage           jsonb NOT NULL DEFAULT '{}'::jsonb,
        trace           jsonb NOT NULL DEFAULT '[]'::jsonb,
        error           text,
        created_by      text NOT NULL,
        created_at      timestamptz NOT NULL DEFAULT now(),
        started_at      timestamptz,
        finished_at     timestamptz
    )
    """,
    "CREATE INDEX runs_tenant ON runs.runs (tenant_id, created_at DESC, id)",
    """
    CREATE TABLE bom.versions (
        id          uuid PRIMARY KEY,
        tenant_id   uuid NOT NULL,
        run_id      uuid NOT NULL REFERENCES runs.runs (id) ON DELETE CASCADE,
        version     integer NOT NULL CHECK (version >= 1),
        parent_id   uuid REFERENCES bom.versions (id),
        content     jsonb NOT NULL,
        reason      text NOT NULL DEFAULT '',
        created_by  text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (run_id, version)
    )
    """,
    """
    CREATE TABLE app.idempotency_keys (
        tenant_id    uuid NOT NULL,
        key          text NOT NULL CHECK (length(key) BETWEEN 8 AND 255),
        request_hash text NOT NULL,
        status_code  integer NOT NULL,
        response     jsonb NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, key)
    )
    """,
    # login: the memberships of one user across tenants, nothing else
    """
    CREATE FUNCTION app.current_user_sub() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(current_setting('app.user_sub', true), '')
    $$
    """,
    f"GRANT EXECUTE ON FUNCTION app.current_user_sub() TO {APP_ROLES}",
    """
    CREATE FUNCTION tenancy.memberships_of(p_sub text)
    RETURNS TABLE (tenant_id uuid, slug text, name text, roles text[], status text)
    LANGUAGE sql STABLE AS $$
        SELECT m.tenant_id, t.slug, t.name, m.roles, m.status
          FROM tenancy.memberships m JOIN tenancy.tenants t ON t.id = m.tenant_id
         WHERE m.user_sub = p_sub AND p_sub = app.current_user_sub()
         ORDER BY t.name
    $$
    """,
    "REVOKE ALL ON FUNCTION tenancy.memberships_of(text) FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION tenancy.memberships_of(text) TO {APP_ROLES}",
    # immutable BOM versions: edits create a new version
    """
    CREATE FUNCTION bom.reject_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'bom.versions are immutable; insert a new version'
            USING ERRCODE = 'insufficient_privilege';
    END $$
    """,
    """CREATE TRIGGER versions_immutable BEFORE UPDATE ON bom.versions
         FOR EACH ROW EXECUTE FUNCTION bom.reject_update()""",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenancy.memberships TO bomagent_app",
    "GRANT SELECT, INSERT ON tenancy.memberships TO bomagent_platform",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON projects.projects, projects.files TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE ON runs.runs TO bomagent_app",
    "GRANT SELECT, INSERT ON bom.versions TO bomagent_app",
    "GRANT SELECT, INSERT, DELETE ON app.idempotency_keys TO bomagent_app",
]
for _table in TABLES:
    UPGRADE.extend(tenant_table_rls(_table))
UPGRADE += [
    """CREATE POLICY member_self ON tenancy.memberships FOR SELECT TO bomagent_app
         USING (user_sub = app.current_user_sub())""",
    """CREATE POLICY member_tenants ON tenancy.tenants FOR SELECT TO bomagent_app
         USING (EXISTS (SELECT 1 FROM tenancy.memberships m
                         WHERE m.tenant_id = tenancy.tenants.id
                           AND m.user_sub = app.current_user_sub()))""",
]
# onboarding (platform role) creates the first owner membership of a new tenant
UPGRADE.append(
    """CREATE POLICY platform_onboarding ON tenancy.memberships TO bomagent_platform
         USING (true) WITH CHECK (true)"""
)

DOWNGRADE = [
    "DROP TABLE app.idempotency_keys",
    "DROP SCHEMA bom CASCADE",
    "DROP SCHEMA runs CASCADE",
    "DROP SCHEMA projects CASCADE",
    "DROP POLICY member_tenants ON tenancy.tenants",
    "DROP FUNCTION tenancy.memberships_of(text)",
    "DROP FUNCTION app.current_user_sub()",
    "DROP TABLE tenancy.memberships",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
