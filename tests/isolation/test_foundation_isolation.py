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


TENANT_TABLES = text(
    """
    SELECT n.nspname || '.' || c.relname AS tbl,
           c.relrowsecurity AS rls, c.relforcerowsecurity AS forced,
           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
     WHERE c.relkind IN ('r', 'p')
       AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    """
)


def test_every_tenant_table_has_forced_rls(db_urls):
    """Catalogue guard, run as admin: pg_class sees every table regardless of grants."""
    from sqlalchemy import create_engine

    admin = create_engine(db_urls.admin)
    with admin.connect() as conn:
        rows = conn.execute(TENANT_TABLES).all()
    admin.dispose()
    assert rows, "expected tenant tables"
    offenders = [r.tbl for r in rows if not (r.rls and r.forced and r.policies > 0)]
    assert offenders == []


def test_catalogue_guard_detects_a_table_without_rls(db_urls):
    from sqlalchemy import create_engine

    admin = create_engine(db_urls.admin)
    try:
        with admin.begin() as conn:
            conn.execute(text("CREATE TABLE public.leaky (tenant_id uuid)"))
            rows = conn.execute(TENANT_TABLES).all()
            conn.execute(text("DROP TABLE public.leaky"))
    finally:
        admin.dispose()
    assert "public.leaky" in [r.tbl for r in rows if not r.rls]


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


async def test_app_cannot_change_its_own_plan_or_slug(app_engine, make_tenant):
    a = await make_tenant()
    for column, value in (("plan", "enterprise"), ("deployment", "silo"), ("slug", "x-y")):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with tenant_transaction(app_engine, a.tenant_id) as conn:
                await conn.execute(text(f"UPDATE tenancy.tenants SET {column} = :v"), {"v": value})
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        res = await conn.execute(text("UPDATE tenancy.tenants SET name = 'Renamed'"))
    assert res.rowcount == 1


async def test_tenant_setting_does_not_leak_between_transactions(app_engine, make_tenant):
    a = await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id):
        pass
    async with platform_transaction(app_engine) as conn:
        value = (await conn.execute(text("SELECT app.current_tenant_id()"))).scalar()
    assert value is None
