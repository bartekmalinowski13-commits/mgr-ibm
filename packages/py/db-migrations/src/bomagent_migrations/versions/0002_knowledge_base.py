"""Knowledge base (ADR-0008): documents, chunks (pgvector + FTS), part catalogue, snapshots.

Scopes: ``global`` rows (tenant_id NULL) are public, read-only for tenants and written only
by the platform role; ``tenant`` rows are visible and writable only in their tenant's
context. Documents are immutable versions: an update inserts a new document that
``supersedes`` the old one, so a snapshot (list of document ids) reproduces retrieval.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

from alembic import op

from bomagent_migrations.rls import APP_ROLES

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCOPE_CHECK = """CHECK ((scope = 'global' AND tenant_id IS NULL)
                     OR (scope = 'tenant' AND tenant_id IS NOT NULL))"""


def _policies(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        # everyone (app and platform) reads the global corpus; tenants read their own rows
        f"""CREATE POLICY kb_read ON {table} FOR SELECT
            USING (scope = 'global' OR tenant_id = app.current_tenant_id())""",
        # the application writes only its own tenant's rows - never global ones
        f"""CREATE POLICY kb_tenant_write ON {table} FOR ALL TO bomagent_app
            USING (scope = 'tenant' AND tenant_id = app.current_tenant_id())
            WITH CHECK (scope = 'tenant' AND tenant_id = app.current_tenant_id())""",
        # the platform pipeline writes only the global corpus - never tenant rows
        f"""CREATE POLICY kb_global_write ON {table} FOR ALL TO bomagent_platform
            USING (scope = 'global' AND tenant_id IS NULL)
            WITH CHECK (scope = 'global' AND tenant_id IS NULL)""",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLES}",
    ]


UPGRADE = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE SCHEMA IF NOT EXISTS kb",
    f"GRANT USAGE ON SCHEMA kb TO {APP_ROLES}",
    f"""
    CREATE TABLE kb.documents (
        id            uuid PRIMARY KEY,
        tenant_id     uuid,
        scope         text NOT NULL CHECK (scope IN ('global', 'tenant')),
        title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
        kind          text NOT NULL DEFAULT 'datasheet'
                      CHECK (kind IN ('datasheet', 'application_note', 'standard',
                                      'component_library', 'correction', 'other')),
        manufacturer  text NOT NULL DEFAULT '',
        source_uri    text NOT NULL DEFAULT '',
        object_key    text,
        mime_type     text NOT NULL,
        sha256        text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
        size_bytes    bigint NOT NULL CHECK (size_bytes >= 0),
        status        text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'indexing', 'indexed', 'failed')),
        error         text,
        supersedes    uuid REFERENCES kb.documents (id),
        superseded_at timestamptz,
        embedding_model text,
        created_by    text NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now(),
        indexed_at    timestamptz,
        {SCOPE_CHECK}
    )
    """,
    """CREATE UNIQUE INDEX documents_dedupe ON kb.documents
         (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), sha256)
         WHERE superseded_at IS NULL""",
    "CREATE INDEX documents_scope ON kb.documents (scope, tenant_id, status)",
    f"""
    CREATE TABLE kb.chunks (
        id              uuid PRIMARY KEY,
        document_id     uuid NOT NULL REFERENCES kb.documents (id) ON DELETE CASCADE,
        tenant_id       uuid,
        scope           text NOT NULL CHECK (scope IN ('global', 'tenant')),
        ordinal         integer NOT NULL CHECK (ordinal >= 0),
        page            integer,
        section         text NOT NULL DEFAULT '',
        content         text NOT NULL CHECK (length(content) > 0),
        content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
        embedding       vector(1024) NOT NULL,
        embedding_model text NOT NULL,
        token_estimate  integer NOT NULL DEFAULT 0,
        injection_suspect boolean NOT NULL DEFAULT false,
        {SCOPE_CHECK},
        UNIQUE (document_id, ordinal)
    )
    """,
    "CREATE INDEX chunks_embedding ON kb.chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX chunks_fts ON kb.chunks USING gin (content_tsv)",
    "CREATE INDEX chunks_scope ON kb.chunks (scope, tenant_id)",
    f"""
    CREATE TABLE kb.parts (
        id           uuid PRIMARY KEY,
        tenant_id    uuid,
        scope        text NOT NULL CHECK (scope IN ('global', 'tenant')),
        document_id  uuid REFERENCES kb.documents (id) ON DELETE CASCADE,
        mpn          text NOT NULL,
        mpn_norm     text GENERATED ALWAYS AS (upper(regexp_replace(mpn, '\\s+', '', 'g'))) STORED,
        manufacturer text NOT NULL DEFAULT '',
        attributes   jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        source       text NOT NULL DEFAULT 'datasheet'
                     CHECK (source IN ('datasheet', 'library', 'user_correction')),
        created_by   text NOT NULL DEFAULT 'system',
        created_at   timestamptz NOT NULL DEFAULT now(),
        {SCOPE_CHECK}
    )
    """,
    "CREATE INDEX parts_mpn ON kb.parts (mpn_norm)",
    "CREATE INDEX parts_scope ON kb.parts (scope, tenant_id)",
    f"""
    CREATE TABLE kb.snapshots (
        id              text NOT NULL,
        tenant_id       uuid,
        scope           text NOT NULL CHECK (scope IN ('global', 'tenant')),
        document_ids    uuid[] NOT NULL,
        embedding_model text NOT NULL,
        created_at      timestamptz NOT NULL DEFAULT now(),
        {SCOPE_CHECK},
        PRIMARY KEY (id)
    )
    """,
    "CREATE INDEX snapshots_tenant ON kb.snapshots (tenant_id)",
    # chunks/parts must belong to the same scope+tenant as their document. FK checks
    # bypass RLS, so without this an app could attach rows to a foreign document id.
    """
    CREATE FUNCTION kb.enforce_document_owner() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        d_scope text;
        d_tenant uuid;
    BEGIN
        IF NEW.document_id IS NULL THEN
            RETURN NEW;
        END IF;
        SELECT scope, tenant_id INTO d_scope, d_tenant FROM kb.documents WHERE id = NEW.document_id;
        IF NOT FOUND OR d_scope IS DISTINCT FROM NEW.scope
           OR d_tenant IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'kb row must have the scope and tenant of its document'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """CREATE TRIGGER chunks_owner BEFORE INSERT OR UPDATE ON kb.chunks
         FOR EACH ROW EXECUTE FUNCTION kb.enforce_document_owner()""",
    """CREATE TRIGGER parts_owner BEFORE INSERT OR UPDATE ON kb.parts
         FOR EACH ROW EXECUTE FUNCTION kb.enforce_document_owner()""",
    *_policies("kb.documents"),
    *_policies("kb.chunks"),
    *_policies("kb.parts"),
    *_policies("kb.snapshots"),
]

DOWNGRADE = ["DROP SCHEMA kb CASCADE"]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
