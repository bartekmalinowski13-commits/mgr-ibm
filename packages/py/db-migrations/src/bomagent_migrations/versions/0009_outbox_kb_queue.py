"""Outbox may also announce knowledge-base uploads (``kb`` queue, M5 KB screen).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UPGRADE = [
    "ALTER TABLE app.outbox DROP CONSTRAINT outbox_queue_check",
    """ALTER TABLE app.outbox ADD CONSTRAINT outbox_queue_check
         CHECK (queue IN ('ingest', 'runs', 'kb'))""",
]
DOWNGRADE = [
    "DELETE FROM app.outbox WHERE queue = 'kb'",
    "ALTER TABLE app.outbox DROP CONSTRAINT outbox_queue_check",
    """ALTER TABLE app.outbox ADD CONSTRAINT outbox_queue_check
         CHECK (queue IN ('ingest', 'runs'))""",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
