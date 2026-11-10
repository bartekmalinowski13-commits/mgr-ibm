"""Tenant-scoped foreign keys (security review of M4).

PostgreSQL checks foreign keys without RLS, so a key on ``id`` alone let a tenant insert
a row pointing at another tenant's project or run (and ``ON DELETE CASCADE`` would then
cross tenants). Parent tables get ``UNIQUE (tenant_id, id)`` and children reference the
pair: a child can only point at a parent of its own tenant.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = [
    "ALTER TABLE projects.projects ADD CONSTRAINT projects_tenant_id UNIQUE (tenant_id, id)",
    "ALTER TABLE runs.runs ADD CONSTRAINT runs_tenant_id UNIQUE (tenant_id, id)",
    "ALTER TABLE bom.versions ADD CONSTRAINT versions_tenant_id UNIQUE (tenant_id, id)",
    # unique keys on foreign ids would also answer "exists in another tenant?"
    "ALTER TABLE projects.files DROP CONSTRAINT files_project_id_name_key",
    """ALTER TABLE projects.files ADD CONSTRAINT files_project_name
         UNIQUE (tenant_id, project_id, name)""",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_run_id_version_key",
    """ALTER TABLE bom.versions ADD CONSTRAINT versions_run_version
         UNIQUE (tenant_id, run_id, version)""",
    "ALTER TABLE projects.files DROP CONSTRAINT files_project_id_fkey",
    """ALTER TABLE projects.files ADD CONSTRAINT files_project_fk FOREIGN KEY
         (tenant_id, project_id) REFERENCES projects.projects (tenant_id, id) ON DELETE CASCADE""",
    "ALTER TABLE runs.runs DROP CONSTRAINT runs_project_id_fkey",
    """ALTER TABLE runs.runs ADD CONSTRAINT runs_project_fk FOREIGN KEY
         (tenant_id, project_id) REFERENCES projects.projects (tenant_id, id) ON DELETE CASCADE""",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_run_id_fkey",
    """ALTER TABLE bom.versions ADD CONSTRAINT versions_run_fk FOREIGN KEY
         (tenant_id, run_id) REFERENCES runs.runs (tenant_id, id) ON DELETE CASCADE""",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_parent_id_fkey",
    """ALTER TABLE bom.versions ADD CONSTRAINT versions_parent_fk FOREIGN KEY
         (tenant_id, parent_id) REFERENCES bom.versions (tenant_id, id)""",
]

DOWNGRADE = [
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_parent_fk",
    """ALTER TABLE bom.versions ADD CONSTRAINT versions_parent_id_fkey FOREIGN KEY
         (parent_id) REFERENCES bom.versions (id)""",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_run_fk",
    """ALTER TABLE bom.versions ADD CONSTRAINT versions_run_id_fkey FOREIGN KEY
         (run_id) REFERENCES runs.runs (id) ON DELETE CASCADE""",
    "ALTER TABLE runs.runs DROP CONSTRAINT runs_project_fk",
    """ALTER TABLE runs.runs ADD CONSTRAINT runs_project_id_fkey FOREIGN KEY
         (project_id) REFERENCES projects.projects (id) ON DELETE CASCADE""",
    "ALTER TABLE projects.files DROP CONSTRAINT files_project_fk",
    """ALTER TABLE projects.files ADD CONSTRAINT files_project_id_fkey FOREIGN KEY
         (project_id) REFERENCES projects.projects (id) ON DELETE CASCADE""",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_run_version",
    "ALTER TABLE bom.versions ADD CONSTRAINT versions_run_id_version_key UNIQUE (run_id, version)",
    "ALTER TABLE projects.files DROP CONSTRAINT files_project_name",
    "ALTER TABLE projects.files ADD CONSTRAINT files_project_id_name_key UNIQUE (project_id, name)",
    "ALTER TABLE bom.versions DROP CONSTRAINT versions_tenant_id",
    "ALTER TABLE runs.runs DROP CONSTRAINT runs_tenant_id",
    "ALTER TABLE projects.projects DROP CONSTRAINT projects_tenant_id",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
