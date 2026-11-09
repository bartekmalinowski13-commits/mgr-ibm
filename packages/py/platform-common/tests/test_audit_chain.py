"""Audit log: append-only, hash chain, tenant isolation (ADR-0011)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from bomagent_common.audit import AuditEvent, emit_audit, verify_chain
from bomagent_common.db import tenant_transaction

pytestmark = pytest.mark.integration


def _event(n: int) -> AuditEvent:
    return AuditEvent(
        action="project.created", object_type="project", object_id=f"p-{n}", after={"n": n}
    )


async def test_chain_links_consecutive_events(app_engine, make_tenant):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        first = await emit_audit(conn, _event(1), tenant)
        second = await emit_audit(conn, _event(2), tenant)
    assert first.seq == 1
    assert first.prev_hash == "0" * 64
    assert second.seq == 2
    assert second.prev_hash == first.hash
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        result = await verify_chain(conn, tenant.tenant_id)
    assert result.ok
    assert result.checked == 2


async def test_chains_are_independent_per_tenant(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        await emit_audit(conn, _event(1), a)
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        rec = await emit_audit(conn, _event(1), b)
    assert rec.seq == 1


async def test_update_and_delete_are_rejected(app_engine, make_tenant):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await emit_audit(conn, _event(1), tenant)
    for stmt in (
        "UPDATE audit.events SET action = 'x.y'",
        "DELETE FROM audit.events",
        "TRUNCATE audit.events",
    ):
        with pytest.raises((ProgrammingError, DBAPIError)):
            async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
                await conn.execute(text(stmt))


async def test_tampering_is_detected(db_urls, app_engine, make_tenant):
    """Even a privileged actor who disables the trigger cannot hide a change."""
    from sqlalchemy import create_engine

    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        for i in range(3):
            await emit_audit(conn, _event(i), tenant)
    admin = create_engine(db_urls.admin)
    with admin.begin() as conn:
        conn.execute(text("ALTER TABLE audit.events DISABLE TRIGGER append_only"))
        conn.execute(
            text("UPDATE audit.events SET after = '{\"n\": 99}' WHERE tenant_id = :t AND seq = 2"),
            {"t": tenant.tenant_id},
        )
        conn.execute(text("ALTER TABLE audit.events ENABLE TRIGGER append_only"))
    admin.dispose()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        result = await verify_chain(conn, tenant.tenant_id)
    assert not result.ok
    assert result.first_broken_seq == 2


def test_audit_event_action_format_is_validated():
    with pytest.raises(ValueError, match="pattern"):
        AuditEvent(action="Created", object_type="x", object_id="1")
