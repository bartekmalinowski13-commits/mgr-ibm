"""Indexes for the per-project lookups on runs and files (audit DATA-01, ARCH-03).

* ``runs.runs (tenant_id, project_id, status)``: ``refuse_if_run_active`` and the run list of
  a project filter on exactly these columns; until now only ``(tenant_id, created_at DESC,
  id)`` existed, so every check scanned all runs of the tenant.
* ``projects.files (tenant_id, project_id)``: listing the files of a project, the project
  size check on upload and the ingest worker all filter by project; the only index was the
  ``UNIQUE (project_id, name)`` constraint, which does not start with the RLS column
  ``tenant_id`` that every query is also filtered by.

Lock behaviour: both indexes are built ``CONCURRENTLY`` (no write lock on a live table), which
PostgreSQL forbids inside a transaction block, so the statements run in Alembic's
``autocommit_block``. A failed concurrent build leaves an INVALID index behind; the
revision therefore drops any leftover of the same name first (``DROP INDEX CONCURRENTLY IF
EXISTS``) and creates it again, which makes a re-run after a failure safe.

No data, grants or RLS policies change. Expand-only: the application does not depend on the
indexes for correctness, so rolling the code back needs no schema change.

Rollback: ``alembic downgrade 0015`` drops both indexes (also concurrently).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

UPGRADE = [
    "DROP INDEX CONCURRENTLY IF EXISTS runs.runs_project_status",
    "CREATE INDEX CONCURRENTLY runs_project_status ON runs.runs (tenant_id, project_id, status)",
    "DROP INDEX CONCURRENTLY IF EXISTS projects.files_project",
    "CREATE INDEX CONCURRENTLY files_project ON projects.files (tenant_id, project_id)",
]

DOWNGRADE = [
    "DROP INDEX CONCURRENTLY IF EXISTS projects.files_project",
    "DROP INDEX CONCURRENTLY IF EXISTS runs.runs_project_status",
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in UPGRADE:
            op.execute(stmt)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in DOWNGRADE:
            op.execute(stmt)
