"""Foundation: tenant context function, tenants, append-only audit log with hash chain.

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

from alembic import op

from bomagent_migrations.rls import APP_ROLES

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE = [
    # ------------------------------------------------------------------ schemas
    "CREATE SCHEMA IF NOT EXISTS app",
    "CREATE SCHEMA IF NOT EXISTS tenancy",
    "CREATE SCHEMA IF NOT EXISTS audit",
    f"GRANT USAGE ON SCHEMA app, tenancy, audit TO {APP_ROLES}",
    # ------------------------------------------------------------------ tenant context
    # NULL when not set or empty -> every RLS predicate `tenant_id = NULL` is false.
    """
    CREATE FUNCTION app.current_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE AS $$
        SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
    $$
    """,
    f"GRANT EXECUTE ON FUNCTION app.current_tenant_id() TO {APP_ROLES}",
    # ------------------------------------------------------------------ tenants
    """
    CREATE TABLE tenancy.tenants (
        id          uuid PRIMARY KEY,
        slug        text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
        name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
        plan        text NOT NULL DEFAULT 'pilot'
                    CHECK (plan IN ('pilot', 'team', 'business', 'enterprise')),
        deployment  text NOT NULL DEFAULT 'pooled' CHECK (deployment IN ('pooled', 'silo')),
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE tenancy.tenants ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE tenancy.tenants FORCE ROW LEVEL SECURITY",
    # application sees and edits only its own tenant row
    """
    CREATE POLICY tenant_self ON tenancy.tenants TO bomagent_app
        USING (id = app.current_tenant_id()) WITH CHECK (id = app.current_tenant_id())
    """,
    # onboarding (platform role) creates tenants and reads them back
    """
    CREATE POLICY platform_onboarding ON tenancy.tenants TO bomagent_platform
        USING (true) WITH CHECK (true)
    """,
    # the application may rename its organisation; plan/deployment/slug change only via
    # the platform role (prevents plan escalation through a mass-assignment bug)
    "GRANT SELECT, UPDATE (name) ON tenancy.tenants TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE ON tenancy.tenants TO bomagent_platform",
    # ------------------------------------------------------------------ audit log
    """
    CREATE TABLE audit.events (
        id           uuid PRIMARY KEY,
        tenant_id    uuid NOT NULL,
        seq          bigint NOT NULL,
        occurred_at  timestamptz NOT NULL,
        actor_type   text NOT NULL CHECK (actor_type IN ('user', 'service', 'api_key', 'system')),
        actor_id     text NOT NULL,
        action       text NOT NULL,
        object_type  text NOT NULL,
        object_id    text NOT NULL,
        source_ip    inet,
        request_id   text,
        trace_id     text,
        before       jsonb,
        after        jsonb,
        prev_hash    text NOT NULL,
        hash         text NOT NULL,
        UNIQUE (tenant_id, seq)
    )
    """,
    "CREATE INDEX events_tenant_time ON audit.events (tenant_id, occurred_at DESC)",
    "CREATE INDEX events_tenant_object ON audit.events (tenant_id, object_type, object_id)",
    # Canonical form hashed in the chain: a JSON array (jsonb text output is deterministic,
    # and array encoding avoids delimiter-injection ambiguities).
    """
    CREATE FUNCTION audit.canonical(e audit.events) RETURNS text
    LANGUAGE sql STABLE AS $$
        SELECT jsonb_build_array(
            e.prev_hash, e.seq, e.id, e.tenant_id,
            to_char(e.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            e.actor_type, e.actor_id, e.action, e.object_type, e.object_id,
            e.source_ip::text, e.request_id, e.trace_id, e.before, e.after
        )::text
    $$
    """,
    """
    CREATE FUNCTION audit.chain_event() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        last_seq  bigint;
        last_hash text;
    BEGIN
        -- serialise writers of one tenant's chain
        PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || NEW.tenant_id::text, 0));
        SELECT seq, hash INTO last_seq, last_hash
          FROM audit.events WHERE tenant_id = NEW.tenant_id
          ORDER BY seq DESC LIMIT 1;
        NEW.seq := COALESCE(last_seq, 0) + 1;
        NEW.prev_hash := COALESCE(last_hash, repeat('0', 64));
        NEW.occurred_at := clock_timestamp();
        NEW.hash := encode(sha256(convert_to(audit.canonical(NEW), 'UTF8')), 'hex');
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER chain_event BEFORE INSERT ON audit.events
        FOR EACH ROW EXECUTE FUNCTION audit.chain_event()
    """,
    """
    CREATE FUNCTION audit.reject_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit.events is append-only (% rejected)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END
    $$
    """,
    """
    CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON audit.events
        FOR EACH ROW EXECUTE FUNCTION audit.reject_mutation()
    """,
    """
    CREATE TRIGGER append_only_truncate BEFORE TRUNCATE ON audit.events
        FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_mutation()
    """,
    """
    CREATE FUNCTION audit.verify_chain(p_tenant uuid)
    RETURNS TABLE (checked bigint, first_broken_seq bigint)
    LANGUAGE plpgsql STABLE AS $$
    DECLARE
        r audit.events;
        expected_prev text := repeat('0', 64);
        expected_seq bigint := 1;
        n bigint := 0;
    BEGIN
        -- Without the matching tenant context RLS would hide every row and the chain would
        -- look "valid" with 0 events - refuse instead of returning a false positive.
        IF p_tenant IS DISTINCT FROM app.current_tenant_id() THEN
            RAISE EXCEPTION 'verify_chain must run in the context of tenant %', p_tenant
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        FOR r IN SELECT * FROM audit.events WHERE tenant_id = p_tenant ORDER BY seq LOOP
            n := n + 1;
            IF r.seq <> expected_seq
               OR r.prev_hash <> expected_prev
               OR r.hash <> encode(sha256(convert_to(audit.canonical(r), 'UTF8')), 'hex') THEN
                checked := n; first_broken_seq := r.seq; RETURN NEXT; RETURN;
            END IF;
            expected_prev := r.hash;
            expected_seq := r.seq + 1;
        END LOOP;
        checked := n; first_broken_seq := NULL; RETURN NEXT;
    END
    $$
    """,
    # Head of a tenant's chain - exported daily to S3 Object Lock (ADR-0011) as the external
    # anchor: rewriting history (even by the table owner) then no longer matches the anchor.
    """
    CREATE FUNCTION audit.chain_head(p_tenant uuid)
    RETURNS TABLE (seq bigint, hash text)
    LANGUAGE sql STABLE AS $$
        SELECT e.seq, e.hash FROM audit.events e
         WHERE e.tenant_id = p_tenant ORDER BY e.seq DESC LIMIT 1
    $$
    """,
    "ALTER TABLE audit.events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE audit.events FORCE ROW LEVEL SECURITY",
    """
    CREATE POLICY tenant_isolation ON audit.events
        USING (tenant_id = app.current_tenant_id())
        WITH CHECK (tenant_id = app.current_tenant_id())
    """,
    f"GRANT SELECT, INSERT ON audit.events TO {APP_ROLES}",
    f"REVOKE UPDATE, DELETE, TRUNCATE ON audit.events FROM {APP_ROLES}",
    f"GRANT EXECUTE ON FUNCTION audit.verify_chain(uuid) TO {APP_ROLES}",
    f"GRANT EXECUTE ON FUNCTION audit.canonical(audit.events) TO {APP_ROLES}",
    f"GRANT EXECUTE ON FUNCTION audit.chain_head(uuid) TO {APP_ROLES}",
]

DOWNGRADE = [
    "DROP SCHEMA audit CASCADE",
    "DROP SCHEMA tenancy CASCADE",
    "DROP SCHEMA app CASCADE",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
