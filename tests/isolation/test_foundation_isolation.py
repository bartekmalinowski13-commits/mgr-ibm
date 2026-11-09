"""Cross-tenant isolation of foundation tables (blocking in CI, marker ``isolation``).

Includes a catalogue-level guard: every table with a ``tenant_id`` column must have RLS
enabled *and forced* with at least one policy - a new table without RLS fails CI.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import platform_transaction, tenant_transaction

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


async def test_every_tenant_table_has_forced_rls(app_engine):
    query = text(
        """
        SELECT c.table_schema || '.' || c.table_name AS tbl,
               cl.relrowsecurity AS rls, cl.relforcerowsecurity AS forced,
               (SELECT count(*) FROM pg_policies p
                 WHERE p.schemaname = c.table_schema AND p.tablename = c.table_name) AS policies
          FROM information_schema.columns c
          JOIN pg_class cl ON cl.relname = c.table_name
          JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = c.table_schema
         WHERE c.column_name = 'tenant_id'
           AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
           AND cl.relkind IN ('r', 'p')
        """
    )
    async with platform_transaction(app_engine) as conn:
        rows = (await conn.execute(query)).all()
    assert rows, "expected tenant tables"
    offenders = [r.tbl for r in rows if not (r.rls and r.forced and r.policies > 0)]
    assert offenders == []


async def test_app_role_cannot_bypass_rls(app_engine):
    async with platform_transaction(app_engine) as conn:
        row = (
            await conn.execute(
                text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert row.rolbypassrls is False
    assert row.rolsuper is False


async def test_no_tenant_context_sees_nothing(app_engine, make_tenant):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await emit_audit(
            conn, AuditEvent(action="x.created", object_type="x", object_id="1"), tenant
        )
    async with platform_transaction(app_engine) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit.events"))).scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM tenancy.tenants"))).scalar() == 0


async def test_tenant_sees_only_own_tenant_and_audit(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        await emit_audit(conn, AuditEvent(action="x.created", object_type="x", object_id="b"), b)
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        tenants = (await conn.execute(text("SELECT id FROM tenancy.tenants"))).scalars().all()
        audit = (await conn.execute(text("SELECT tenant_id FROM audit.events"))).scalars().all()
    assert tenants == [a.tenant_id]
    assert b.tenant_id not in audit


async def test_cannot_write_audit_event_for_other_tenant(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await emit_audit(
                conn, AuditEvent(action="x.created", object_type="x", object_id="1"), b
            )


async def test_cannot_rename_other_tenant(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        res = await conn.execute(
            text("UPDATE tenancy.tenants SET name = 'pwned' WHERE id = :id"), {"id": b.tenant_id}
        )
    assert res.rowcount == 0


async def test_tenant_setting_does_not_leak_between_transactions(app_engine, make_tenant):
    a = await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id):
        pass
    async with platform_transaction(app_engine) as conn:
        value = (await conn.execute(text("SELECT app.current_tenant_id()"))).scalar()
    assert value is None
