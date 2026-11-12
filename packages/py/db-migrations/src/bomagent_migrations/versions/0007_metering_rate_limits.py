"""Usage metering and request rate windows (M4; ARCHITECTURE: metering, limits per
tenant and API key - SECURITY.md).

``metering.usage_daily`` accumulates per tenant and day what plan limits and the
thesis cost metric need (runs, LLM calls, tokens, cost, uploads). ``app.rate_windows``
counts requests per subject (user or API key) in one-minute windows; it is UNLOGGED
(losing counters on a crash is harmless) and shared by all API replicas.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

from alembic import op

from bomagent_migrations.rls import tenant_table_rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UPGRADE = [
    "CREATE SCHEMA IF NOT EXISTS metering",
    "GRANT USAGE ON SCHEMA metering TO bomagent_app",
    """
    CREATE TABLE metering.usage_daily (
        tenant_id      uuid NOT NULL REFERENCES tenancy.tenants (id) ON DELETE CASCADE,
        day            date NOT NULL,
        runs           integer NOT NULL DEFAULT 0 CHECK (runs >= 0),
        llm_calls      integer NOT NULL DEFAULT 0 CHECK (llm_calls >= 0),
        input_tokens   bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
        output_tokens  bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
        cost_eur       numeric(14, 6) NOT NULL DEFAULT 0 CHECK (cost_eur >= 0),
        files_uploaded integer NOT NULL DEFAULT 0 CHECK (files_uploaded >= 0),
        bytes_uploaded bigint NOT NULL DEFAULT 0 CHECK (bytes_uploaded >= 0),
        PRIMARY KEY (tenant_id, day)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE ON metering.usage_daily TO bomagent_app",
    *tenant_table_rls("metering.usage_daily"),
    """
    CREATE UNLOGGED TABLE app.rate_windows (
        tenant_id    uuid NOT NULL,
        subject      text NOT NULL CHECK (length(subject) BETWEEN 1 AND 300),
        window_start timestamptz NOT NULL,
        hits         integer NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, subject, window_start)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON app.rate_windows TO bomagent_app",
    *tenant_table_rls("app.rate_windows"),
]

DOWNGRADE = [
    "DROP TABLE app.rate_windows",
    "DROP SCHEMA metering CASCADE",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
