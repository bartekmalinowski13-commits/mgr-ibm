"""Projects, uploaded designs and BOM runs (M4).

Every table is tenant data: ``tenant_id`` + standard RLS (``tenant_table_rls``). Large
artefacts (design files, parsed design, BOM, trace) live in S3 under the tenant prefix;
rows keep object keys, status and accounting. Idempotency of run creation is enforced by
a unique ``(tenant_id, idempotency_key)``.

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

UPGRADE = [
    """
    CREATE TABLE app.projects (
        id          uuid PRIMARY KEY,
        tenant_id   uuid NOT NULL REFERENCES tenancy.tenants(id),
        name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
        created_by  text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX projects_tenant_created ON app.projects (tenant_id, created_at DESC, id DESC)",
    *tenant_table_rls("app.projects"),
    """
    CREATE TABLE app.designs (
        id            uuid PRIMARY KEY,
        tenant_id     uuid NOT NULL REFERENCES tenancy.tenants(id),
        project_id    uuid NOT NULL REFERENCES app.projects(id),
        filenames     text[] NOT NULL CHECK (cardinality(filenames) BETWEEN 1 AND 50),
        status        text NOT NULL DEFAULT 'awaiting_upload'
                      CHECK (status IN ('awaiting_upload', 'uploaded', 'parsed', 'failed')),
        source_format text,
        components    integer,
        confidence    real,
        limitations   jsonb NOT NULL DEFAULT '[]'::jsonb,
        parsed_key    text,
        error         text,
        created_by    text NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX designs_project ON app.designs (tenant_id, project_id, created_at DESC)",
    *tenant_table_rls("app.designs"),
    """
    CREATE TABLE app.runs (
        id               uuid PRIMARY KEY,
        tenant_id        uuid NOT NULL REFERENCES tenancy.tenants(id),
        design_id        uuid NOT NULL REFERENCES app.designs(id),
        variant          text NOT NULL CHECK (variant IN ('A', 'B', 'A-sdk')),
        model_id         text NOT NULL,
        status           text NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'running', 'completed', 'failed')),
        idempotency_key  text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
        requirements     jsonb NOT NULL DEFAULT '{}'::jsonb,
        budget           jsonb,
        bom_key          text,
        result_key       text,
        usage            jsonb,
        error            text,
        created_by       text NOT NULL,
        created_at       timestamptz NOT NULL DEFAULT now(),
        started_at       timestamptz,
        finished_at      timestamptz,
        UNIQUE (tenant_id, idempotency_key)
    )
    """,
    "CREATE INDEX runs_tenant_created ON app.runs (tenant_id, created_at DESC, id DESC)",
    "CREATE INDEX runs_design ON app.runs (tenant_id, design_id)",
    *tenant_table_rls("app.runs"),
    f"GRANT SELECT, INSERT, UPDATE ON app.projects, app.designs, app.runs TO {APP_ROLES}",
]

DOWNGRADE = ["DROP TABLE app.runs", "DROP TABLE app.designs", "DROP TABLE app.projects"]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
