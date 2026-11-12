"""PostgreSQL message queue (``app.queue_messages``) for the Supabase pilot deployment.

The lightweight deployment variant has no SQS: ``bomagent_common.messaging.PostgresQueue``
keeps the same envelope (``Message``) in this table with SQS semantics - a visibility
timeout, a receive count and dead-lettering (``dead_at``) after N receives. AWS keeps SQS;
the table simply stays empty there.

Who may do what (security review):

* ``bomagent_app`` (API, tenant context) may only **INSERT** rows of the tenant in
  ``app.tenant_id`` (standard ``tenant_isolation`` policy). It has no SELECT, UPDATE or
  DELETE: a request can never read or consume queued messages, not even its own.
* ``bomagent_platform`` consumes across tenants, like the SQS consumers do in AWS: a
  queue is shared by all tenants, so a consumer cannot know the tenant before it has read
  the row. It gets explicit per-command policies (SELECT, UPDATE, DELETE - **no INSERT**)
  and column-level UPDATE only on the delivery bookkeeping (``visible_at``,
  ``receive_count``, ``receipt``, ``dead_at``), so it can neither forge a message nor move
  one to another tenant. This follows the existing treatment of the platform role
  (``platform_onboarding`` on ``tenancy.tenants``/``memberships``, ``kb_global_write``):
  narrow, named policies ``TO bomagent_platform`` instead of BYPASSRLS. After receiving,
  the worker restores the message's ``TenantContext`` and touches tenant data only with
  the app role in that tenant's RLS context (``process_one``), exactly as with SQS.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-12
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLE = "app.queue_messages"

UPGRADE = [
    f"""
    CREATE TABLE {TABLE} (
        id            uuid PRIMARY KEY,
        tenant_id     uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        queue         text NOT NULL CHECK (queue ~ '^[a-z][a-z0-9_-]{{0,62}}$'),
        message       jsonb NOT NULL,
        enqueued_at   timestamptz NOT NULL DEFAULT now(),
        visible_at    timestamptz NOT NULL DEFAULT now(),
        receive_count integer NOT NULL DEFAULT 0 CHECK (receive_count >= 0),
        receipt       uuid,
        dead_at       timestamptz,
        -- RLS checks the row's tenant, workers act on the envelope's: they must agree
        CONSTRAINT queue_messages_envelope_tenant CHECK (message->>'tenant_id' = tenant_id::text)
    )
    """,
    # receive: oldest visible live message of one queue
    f"CREATE INDEX queue_messages_ready ON {TABLE} (queue, visible_at) WHERE dead_at IS NULL",
    f"CREATE INDEX queue_messages_dead ON {TABLE} (dead_at) WHERE dead_at IS NOT NULL",
    f"GRANT INSERT ON {TABLE} TO bomagent_app",
    f"GRANT SELECT, DELETE ON {TABLE} TO bomagent_platform",
    f"GRANT UPDATE (visible_at, receive_count, receipt, dead_at) ON {TABLE} TO bomagent_platform",
    *tenant_table_rls(TABLE),
    f"CREATE POLICY queue_consumer_read ON {TABLE} FOR SELECT TO bomagent_platform USING (true)",
    f"""CREATE POLICY queue_consumer_update ON {TABLE} FOR UPDATE TO bomagent_platform
         USING (true) WITH CHECK (true)""",
    f"CREATE POLICY queue_consumer_delete ON {TABLE} FOR DELETE TO bomagent_platform USING (true)",
]

DOWNGRADE = [f"DROP TABLE {TABLE}"]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
