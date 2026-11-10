"""Isolation of M4 platform tables (projects, files, runs, BOM versions, memberships)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bomagent_common.db import platform_transaction, tenant_transaction, user_transaction

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


async def _project(engine, tenant) -> tuple[uuid.UUID, uuid.UUID]:
    pid, rid = uuid.uuid4(), uuid.uuid4()
    async with tenant_transaction(engine, tenant.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, created_by)"
                " VALUES (:i, :t, 'p', 'u')"
            ),
            {"i": pid, "t": tenant.tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant,"
                " runtime, model_id, created_by) VALUES (:r, :t, :p, 'B',"
                " 'langgraph_b', 'fake-closed', 'u')"
            ),
            {"r": rid, "t": tenant.tenant_id, "p": pid},
        )
        await conn.execute(
            text(
                "INSERT INTO bom.versions (id, tenant_id, run_id, version,"
                " content, created_by) VALUES (:i, :t, :r, 1, CAST(:c AS jsonb),"
                " 'u')"
            ),
            {"i": uuid.uuid4(), "t": tenant.tenant_id, "r": rid, "c": json.dumps({"items": []})},
        )
    return pid, rid


@pytest.mark.parametrize("table", ["projects.projects", "runs.runs", "bom.versions"])
async def test_rows_invisible_to_other_tenant(app_engine, make_tenant, table):
    a, b = await make_tenant(), await make_tenant()
    await _project(app_engine, b)
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 1


async def test_cannot_attach_run_to_foreign_project(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    pid_b, _ = await _project(app_engine, b)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO runs.runs (id, tenant_id, project_id, variant,"
                    " runtime, model_id, created_by) VALUES (:r, :t, :p, 'B',"
                    " 'x', 'y', 'u')"
                ),
                {"r": uuid.uuid4(), "t": b.tenant_id, "p": pid_b},
            )


async def test_bom_versions_are_immutable(app_engine, make_tenant):
    a = await make_tenant()
    await _project(app_engine, a)
    with pytest.raises(DBAPIError, match=r"immutable|permission denied"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(text("UPDATE bom.versions SET reason = 'x'"))


async def test_memberships_lookup_returns_only_the_users_own(
    app_engine, platform_engine, make_tenant
):
    a, b = await make_tenant(), await make_tenant()
    async with platform_transaction(platform_engine) as conn:
        for tenant, sub in ((a, "alice"), (b, "bob"), (b, "alice")):
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email, roles)"
                    " VALUES (:t, :s, :e, ARRAY['engineer'])"
                ),
                {"t": tenant.tenant_id, "s": sub, "e": f"{sub}@x.eu"},
            )
    async with user_transaction(app_engine, "alice") as conn:  # login, no tenant context
        mine = await conn.execute(text("SELECT tenant_id FROM tenancy.memberships_of('alice')"))
        rows = mine.scalars().all()
        spoof = await conn.execute(text("SELECT count(*) FROM tenancy.memberships_of('bob')"))
        visible = await conn.execute(text("SELECT user_sub FROM tenancy.memberships"))
        subs = visible.scalars().all()
        tenants = (await conn.execute(text("SELECT count(*) FROM tenancy.tenants"))).scalar()
        assert spoof.scalar() == 0  # cannot list another user's memberships
    assert set(rows) == {a.tenant_id, b.tenant_id}
    assert set(subs) == {"alice"}  # bob's row in tenant b stays hidden
    assert tenants == 2
    async with platform_transaction(app_engine) as conn:  # no context: nothing
        assert (await conn.execute(text("SELECT count(*) FROM tenancy.memberships"))).scalar() == 0
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        in_a = (await conn.execute(text("SELECT user_sub FROM tenancy.memberships"))).scalars()
        assert in_a.all() == ["alice"]
