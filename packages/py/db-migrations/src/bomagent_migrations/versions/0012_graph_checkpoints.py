"""LangGraph checkpoints per run, tenant-scoped (ADR-0007, DECISIONS_LOG 2026-11-10).

The standard ``langgraph-checkpoint-postgres`` tables live in ``public`` without a tenant
column, so a run's state (customer design data) would share one table across tenants.
These tables carry ``tenant_id`` with the standard RLS policy and reference the run
(``(tenant_id, run_id)``, cascade): checkpoints live and die with their run.

* ``runs.graph_checkpoints`` - one row per checkpoint (serialised with LangGraph's
  serializer: ``*_type`` + bytes), parent link for history.
* ``runs.graph_writes`` - pending writes of tasks between checkpoints (resume after a
  worker crash without re-running finished branches).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-11
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE runs.graph_checkpoints (
        tenant_id            uuid NOT NULL,
        run_id               uuid NOT NULL,
        checkpoint_ns        text NOT NULL DEFAULT '',
        checkpoint_id        text NOT NULL,
        parent_checkpoint_id text,
        checkpoint_type      text NOT NULL,
        checkpoint           bytea NOT NULL,
        metadata_type        text NOT NULL,
        metadata             bytea NOT NULL,
        created_at           timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, run_id, checkpoint_ns, checkpoint_id),
        FOREIGN KEY (tenant_id, run_id) REFERENCES runs.runs (tenant_id, id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE runs.graph_writes (
        tenant_id     uuid NOT NULL,
        run_id        uuid NOT NULL,
        checkpoint_ns text NOT NULL DEFAULT '',
        checkpoint_id text NOT NULL,
        task_id       text NOT NULL,
        idx           integer NOT NULL,
        channel       text NOT NULL,
        value_type    text NOT NULL,
        value         bytea NOT NULL,
        task_path     text NOT NULL DEFAULT '',
        PRIMARY KEY (tenant_id, run_id, checkpoint_ns, checkpoint_id, task_id, idx),
        FOREIGN KEY (tenant_id, run_id) REFERENCES runs.runs (tenant_id, id) ON DELETE CASCADE
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON runs.graph_checkpoints TO bomagent_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON runs.graph_writes TO bomagent_app",
    *tenant_table_rls("runs.graph_checkpoints"),
    *tenant_table_rls("runs.graph_writes"),
]

DOWNGRADE = ["DROP TABLE runs.graph_writes", "DROP TABLE runs.graph_checkpoints"]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
