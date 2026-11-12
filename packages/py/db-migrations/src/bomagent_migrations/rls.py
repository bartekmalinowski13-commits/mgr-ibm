"""SQL helpers used by migrations to declare tenant tables consistently."""

from __future__ import annotations

APP_ROLES = "bomagent_app, bomagent_platform"


def tenant_table_rls(table: str) -> list[str]:
    """Standard isolation for a table with a ``tenant_id`` column.

    ``FORCE`` makes the policy apply to the table owner too (defence in depth).
    No tenant context -> ``app.current_tenant_id()`` is NULL -> no rows match.
    """
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app.current_tenant_id())
            WITH CHECK (tenant_id = app.current_tenant_id())""",
    ]
