"""Sample projects: ``projects.projects.sample_key``.

A project added by the platform as a sample (``[Sample] ...``) carries the catalogue key of its
sample. The partial unique index makes seeding idempotent per organisation at the database
level (a sample exists at most once per tenant), and the plan's project quota ignores them
(``bomagent_api.plans.check_new_project``). Only sample projects can be deleted through the API.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

UPGRADE = [
    """ALTER TABLE projects.projects ADD COLUMN sample_key text
         CHECK (sample_key IS NULL OR length(sample_key) BETWEEN 1 AND 64)""",
    """CREATE UNIQUE INDEX projects_sample_key ON projects.projects (tenant_id, sample_key)
         WHERE sample_key IS NOT NULL""",
]

DOWNGRADE = [
    "DROP INDEX projects.projects_sample_key",
    "ALTER TABLE projects.projects DROP COLUMN sample_key",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
