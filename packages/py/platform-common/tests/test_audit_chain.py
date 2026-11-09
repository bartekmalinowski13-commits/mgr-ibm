"""Audit log: append-only, hash chain, tenant isolation (ADR-0011)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from bomagent_common.audit import AuditEvent, ChainAnchor, chain_head, emit_audit, verify_chain
from bomagent_common.db import platform_transaction, tenant_transaction

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


@pytest.mark.parametrize(
    "stmt",
    ["UPDATE audit.events SET action = 'x.y'", "DELETE FROM audit.events", "TRUNCATE audit.events"],
)
async def test_app_role_has_no_update_delete_privileges(app_engine, make_tenant, stmt):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await emit_audit(conn, _event(1), tenant)
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            await conn.execute(text(stmt))


@pytest.mark.parametrize(
    ("stmt", "op"),
    [
        ("UPDATE audit.events SET action = 'x.y'", "UPDATE"),
        ("DELETE FROM audit.events", "DELETE"),
        ("TRUNCATE audit.events", "TRUNCATE"),
    ],
)
async def test_append_only_trigger_blocks_even_the_owner(db_urls, make_tenant, stmt, op):
    """The table owner (migrator) has full privileges - the trigger still refuses."""
    from bomagent_common.db import make_engine

    tenant = await make_tenant()
    owner = make_engine(db_urls.migrator)
    try:
        async with tenant_transaction(owner, tenant.tenant_id) as conn:
            await emit_audit(conn, _event(1), tenant)
        with pytest.raises(DBAPIError, match=f"append-only \\({op} rejected\\)"):
            async with tenant_transaction(owner, tenant.tenant_id) as conn:
                await conn.execute(text(stmt))
    finally:
        await owner.dispose()


async def test_concurrent_writers_keep_a_valid_chain(app_engine, make_tenant):
    tenant = await make_tenant()

    async def write(i: int) -> None:
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            await emit_audit(conn, _event(i), tenant)

    await asyncio.gather(*(write(i) for i in range(12)))
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        result = await verify_chain(conn, tenant.tenant_id)
    assert result.ok
    assert result.checked == 12


async def test_verify_chain_refuses_wrong_or_missing_context(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        await emit_audit(conn, _event(1), a)
    with pytest.raises(DBAPIError, match="context of tenant"):
        async with tenant_transaction(app_engine, b.tenant_id) as conn:
            await verify_chain(conn, a.tenant_id)
    with pytest.raises(DBAPIError, match="context of tenant"):
        async with platform_transaction(app_engine) as conn:
            await verify_chain(conn, a.tenant_id)


async def _tamper(db_urls, tenant_id, *, rehash: bool) -> None:
    """Simulate a privileged attacker editing event 2 (optionally re-hashing the rest)."""
    from sqlalchemy import create_engine

    admin = create_engine(db_urls.admin)
    with admin.begin() as conn:
        conn.execute(text("ALTER TABLE audit.events DISABLE TRIGGER append_only"))
        conn.execute(
            text("UPDATE audit.events SET after = '{\"n\": 99}' WHERE tenant_id = :t AND seq = 2"),
            {"t": tenant_id},
        )
        if rehash:
            rows = (
                conn.execute(
                    text(
                        "SELECT seq FROM audit.events"
                        " WHERE tenant_id = :t AND seq >= 2 ORDER BY seq"
                    ),
                    {"t": tenant_id},
                )
                .scalars()
                .all()
            )
            for seq in rows:
                conn.execute(
                    text(
                        """UPDATE audit.events e SET
                             prev_hash = (SELECT hash FROM audit.events p
                                           WHERE p.tenant_id = e.tenant_id AND p.seq = e.seq - 1)
                           WHERE tenant_id = :t AND seq = :s"""
                    ),
                    {"t": tenant_id, "s": seq},
                )
                conn.execute(
                    text(
                        """UPDATE audit.events e SET hash = encode(sha256(convert_to(
                             audit.canonical(e), 'UTF8')), 'hex')
                           WHERE tenant_id = :t AND seq = :s"""
                    ),
                    {"t": tenant_id, "s": seq},
                )
        conn.execute(text("ALTER TABLE audit.events ENABLE TRIGGER append_only"))
    admin.dispose()


async def test_tampering_without_rehash_is_detected(db_urls, app_engine, make_tenant):
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        for i in range(3):
            await emit_audit(conn, _event(i), tenant)
    await _tamper(db_urls, tenant.tenant_id, rehash=False)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        result = await verify_chain(conn, tenant.tenant_id)
    assert not result.ok
    assert result.first_broken_seq == 2


async def test_rehashed_rewrite_is_caught_by_exported_anchor(db_urls, app_engine, make_tenant):
    """A full re-hash passes recomputation; the external anchor (Object Lock) catches it."""
    tenant = await make_tenant()
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        for i in range(3):
            await emit_audit(conn, _event(i), tenant)
        anchor = await chain_head(conn, tenant.tenant_id)
    assert anchor is not None
    assert anchor.seq == 3
    await _tamper(db_urls, tenant.tenant_id, rehash=True)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        plain = await verify_chain(conn, tenant.tenant_id)
        anchored = await verify_chain(conn, tenant.tenant_id, [anchor])
        empty_head = await chain_head(conn, (await make_tenant()).tenant_id)
    assert plain.ok  # recomputation alone cannot see a consistent rewrite
    assert not anchored.ok
    assert anchored.first_broken_seq == 3
    assert empty_head is None
    assert ChainAnchor(1, "x").seq == 1


def test_audit_event_action_format_is_validated():
    with pytest.raises(ValueError, match="pattern"):
        AuditEvent(action="Created", object_type="x", object_id="1")
