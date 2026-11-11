"""Deferred low findings of the second M4 review.

* outbox: ``dead_at`` marks rows that exhausted their delivery attempts (the relay stops
  retrying them); the app role may delete sent rows (retention cleanup);
* composite ``(tenant_id, id)`` foreign keys in ``kb.*`` and ``api_keys.replaced_by``, as
  migration 0005 did for projects, runs and BOM versions. PostgreSQL checks foreign keys
  without RLS, so a key on ``id`` alone could point at another tenant's row.

In ``kb.*`` the original single-column keys stay: global rows have ``tenant_id`` NULL,
which a composite key does not check, and they still need ``ON DELETE CASCADE``.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UPGRADE = [
    "ALTER TABLE app.outbox ADD COLUMN dead_at timestamptz",
    "DROP INDEX app.outbox_pending",
    """CREATE INDEX outbox_pending ON app.outbox (tenant_id, created_at)
         WHERE sent_at IS NULL AND dead_at IS NULL""",
    "CREATE INDEX outbox_sent ON app.outbox (tenant_id, sent_at) WHERE sent_at IS NOT NULL",
    "GRANT DELETE ON app.outbox TO bomagent_app",
    # api_keys.replaced_by
    "ALTER TABLE tenancy.api_keys ADD CONSTRAINT api_keys_tenant_id UNIQUE (tenant_id, id)",
    "ALTER TABLE tenancy.api_keys DROP CONSTRAINT api_keys_replaced_by_fkey",
    """ALTER TABLE tenancy.api_keys ADD CONSTRAINT api_keys_replaced_by_fk FOREIGN KEY
         (tenant_id, replaced_by) REFERENCES tenancy.api_keys (tenant_id, id)""",
    # kb.*
    "ALTER TABLE kb.documents ADD CONSTRAINT documents_tenant_id UNIQUE (tenant_id, id)",
    """ALTER TABLE kb.documents ADD CONSTRAINT documents_supersedes_fk FOREIGN KEY
         (tenant_id, supersedes) REFERENCES kb.documents (tenant_id, id)""",
    """ALTER TABLE kb.chunks ADD CONSTRAINT chunks_document_fk FOREIGN KEY
         (tenant_id, document_id) REFERENCES kb.documents (tenant_id, id) ON DELETE CASCADE""",
    """ALTER TABLE kb.parts ADD CONSTRAINT parts_document_fk FOREIGN KEY
         (tenant_id, document_id) REFERENCES kb.documents (tenant_id, id) ON DELETE CASCADE""",
]

DOWNGRADE = [
    "ALTER TABLE kb.parts DROP CONSTRAINT parts_document_fk",
    "ALTER TABLE kb.chunks DROP CONSTRAINT chunks_document_fk",
    "ALTER TABLE kb.documents DROP CONSTRAINT documents_supersedes_fk",
    "ALTER TABLE kb.documents DROP CONSTRAINT documents_tenant_id",
    "ALTER TABLE tenancy.api_keys DROP CONSTRAINT api_keys_replaced_by_fk",
    """ALTER TABLE tenancy.api_keys ADD CONSTRAINT api_keys_replaced_by_fkey FOREIGN KEY
         (replaced_by) REFERENCES tenancy.api_keys (id)""",
    "ALTER TABLE tenancy.api_keys DROP CONSTRAINT api_keys_tenant_id",
    "REVOKE DELETE ON app.outbox FROM bomagent_app",
    "DROP INDEX app.outbox_sent",
    "DROP INDEX app.outbox_pending",
    "CREATE INDEX outbox_pending ON app.outbox (tenant_id, created_at) WHERE sent_at IS NULL",
    "ALTER TABLE app.outbox DROP COLUMN dead_at",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
