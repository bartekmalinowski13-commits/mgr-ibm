"""Human review of a run's BOM (M4 part 2).

The agents' BOM (``bom_key``) stays immutable - it is the experiment's output. A reviewer's
edits go to a separate reviewed copy (``reviewed_bom_key``) with ``user`` provenance;
before/after values are in the audit log.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    ALTER TABLE app.runs
        ADD COLUMN reviewed_bom_key text,
        ADD COLUMN reviewed_by      text,
        ADD COLUMN reviewed_at      timestamptz,
        ADD COLUMN review_edits     integer NOT NULL DEFAULT 0 CHECK (review_edits >= 0)
    """,
]

DOWNGRADE = [
    """
    ALTER TABLE app.runs
        DROP COLUMN review_edits,
        DROP COLUMN reviewed_at,
        DROP COLUMN reviewed_by,
        DROP COLUMN reviewed_bom_key
    """,
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
