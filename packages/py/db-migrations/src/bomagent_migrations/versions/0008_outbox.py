"""Transactional outbox (security review of M4).

Queue messages are inserted in the same transaction as the row they announce (file
uploaded, run queued) and sent after commit; a periodic relay sends what is left, so a
failed queue send can no longer leave a file ``uploaded`` or a run ``queued`` forever.
Consumers are idempotent (at-least-once delivery).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE app.outbox (
        id         uuid PRIMARY KEY,
        tenant_id  uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        queue      text NOT NULL CHECK (queue IN ('ingest', 'runs')),
        message    jsonb NOT NULL,
        attempts   integer NOT NULL DEFAULT 0,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        sent_at    timestamptz
    )
    """,
    "CREATE INDEX outbox_pending ON app.outbox (tenant_id, created_at) WHERE sent_at IS NULL",
    "GRANT SELECT, INSERT, UPDATE ON app.outbox TO bomagent_app",
    *tenant_table_rls("app.outbox"),
]

DOWNGRADE = ["DROP TABLE app.outbox"]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
