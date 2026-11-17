"""SEC-15: onboarding only through ``tenancy.create_organization``; the platform role cannot
insert tenants or memberships, nor attach an owner to an existing tenant."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from bomagent_common.db import platform_transaction, tenant_transaction, user_transaction

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

CREATE = "SELECT tenancy.create_organization(:i, :s, :n, :sub, :e, :d)"


def _args(slug: str | None = None, sub: str = "owner-1") -> dict[str, object]:
    tid = uuid.uuid4()
    return {
        "i": tid,
        "s": slug or f"o-{tid.hex[:12]}",
        "n": "Org",
        "sub": sub,
        "e": "Owner@X.eu",
        "d": "Owner",
    }


async def test_platform_creates_a_tenant_with_exactly_one_owner(platform_engine, app_engine):
    a = _args()
    async with platform_transaction(platform_engine) as conn:
        assert (await conn.execute(text(CREATE), a)).scalar() == a["i"]
    async with tenant_transaction(app_engine, a["i"]) as conn:
        rows = (
            await conn.execute(text("SELECT user_sub, email, roles FROM tenancy.memberships"))
        ).all()
        slug = (await conn.execute(text("SELECT slug FROM tenancy.tenants"))).scalar()
    assert [(r.user_sub, r.email, r.roles) for r in rows] == [("owner-1", "owner@x.eu", ["owner"])]
    assert slug == a["s"]


async def test_the_function_does_not_leak_or_change_the_callers_tenant_context(platform_engine):
    a = _args()
    async with platform_transaction(platform_engine) as conn:
        before = (
            await conn.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar()
        await conn.execute(text(CREATE), a)
        after = (await conn.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
        assert (before or "") == (after or "") == ""
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a["i"])})
        await conn.execute(text(CREATE), _args())
        kept = (await conn.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
        assert kept == str(a["i"])  # restored to what the caller had


async def test_platform_role_cannot_insert_tenants_or_memberships_directly(
    platform_engine, make_tenant
):
    t = await make_tenant()
    with pytest.raises(DBAPIError, match="permission denied"):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(
                text("INSERT INTO tenancy.tenants (id, slug, name) VALUES (:i, :s, 'x')"),
                {"i": uuid.uuid4(), "s": f"x-{uuid.uuid4().hex[:10]}"},
            )
    with pytest.raises(DBAPIError, match="permission denied"):  # the audit's owner-injection
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email, roles)"
                    " VALUES (:t, 'evil', 'e@x.eu', ARRAY['owner'])"
                ),
                {"t": t.tenant_id},
            )
    with pytest.raises(DBAPIError, match="permission denied"):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(text("SELECT count(*) FROM tenancy.memberships"))


async def test_function_cannot_attach_an_owner_to_an_existing_tenant(
    platform_engine, app_engine, make_tenant
):
    victim = await make_tenant()
    evil = _args(sub="evil") | {"i": victim.tenant_id}
    with pytest.raises(IntegrityError):  # tenants.id is the primary key
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(text(CREATE), evil)
    async with tenant_transaction(app_engine, victim.tenant_id) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM tenancy.memberships"))).scalar() == 0


async def test_duplicate_slug_is_a_unique_violation_and_leaves_nothing_behind(
    platform_engine, app_engine
):
    first = _args(slug=f"dup-{uuid.uuid4().hex[:8]}")
    async with platform_transaction(platform_engine) as conn:
        await conn.execute(text(CREATE), first)
    second = _args(slug=str(first["s"]))
    with pytest.raises(IntegrityError):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(text(CREATE), second)
    async with tenant_transaction(app_engine, second["i"]) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM tenancy.tenants"))).scalar() == 0


async def test_application_role_cannot_call_the_function(app_engine):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with user_transaction(app_engine, "alice") as conn:
            await conn.execute(text(CREATE), _args())


async def test_tenants_stay_isolated_after_onboarding(platform_engine, app_engine):
    a, b = _args(), _args(sub="owner-2")
    async with platform_transaction(platform_engine) as conn:
        await conn.execute(text(CREATE), a)
        await conn.execute(text(CREATE), b)
    async with tenant_transaction(app_engine, a["i"]) as conn:
        subs = (await conn.execute(text("SELECT user_sub FROM tenancy.memberships"))).scalars()
        assert subs.all() == ["owner-1"]
        ids = (await conn.execute(text("SELECT id FROM tenancy.tenants"))).scalars().all()
        assert ids == [a["i"]]


async def test_platform_role_still_reads_and_updates_tenants_for_maintenance(
    platform_engine, make_tenant
):
    t = await make_tenant()
    async with platform_transaction(platform_engine) as conn:
        assert t.tenant_id in (await conn.execute(text("SELECT id FROM tenancy.tenants"))).scalars()
        upd = await conn.execute(
            text("UPDATE tenancy.tenants SET plan = 'team' WHERE id = :i"), {"i": t.tenant_id}
        )
        assert upd.rowcount == 1
    with pytest.raises(DBAPIError, match=r"permission denied|row-level security"):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(
                text("DELETE FROM tenancy.tenants WHERE id = :i"), {"i": t.tenant_id}
            )


async def test_function_definition_is_hardened(platform_engine):
    async with platform_transaction(platform_engine) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT pg_get_userbyid(p.proowner) AS owner, p.prosecdef, p.proconfig,"
                    " r.rolsuper, r.rolbypassrls, p.proacl::text AS acl"
                    " FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner"
                    " WHERE p.oid = 'tenancy.create_organization(uuid,text,text,text,text,text)'"
                    "::regprocedure"
                )
            )
        ).one()
    assert row.owner == "bomagent_migrator"
    assert row.prosecdef is True
    assert any(c.startswith("search_path=") and "pg_temp" in c for c in row.proconfig)
    assert not row.rolsuper
    assert not row.rolbypassrls
    # only the owner and bomagent_platform: no PUBLIC entry (empty grantee before the '=')
    grantees = {entry.split("=")[0] for entry in row.acl.strip("{}").split(",")}
    assert grantees == {"bomagent_migrator", "bomagent_platform"}
