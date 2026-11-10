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


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (
            "INSERT INTO runs.runs (id, tenant_id, project_id, variant, runtime, model_id,"
            " created_by) VALUES (:i, :t, :p, 'B', 'langgraph_b', 'fake-closed', 'u')",
            "project",
        ),
        (
            "INSERT INTO projects.files (id, tenant_id, project_id, name, object_key, sha256,"
            " size_bytes, created_by) VALUES (:i, :t, :p, 'f', 'k', repeat('a', 64), 1, 'u')",
            "project",
        ),
        (
            "INSERT INTO bom.versions (id, tenant_id, run_id, version, content, created_by)"
            " VALUES (:i, :t, :p, 1, '{}'::jsonb, 'u')",
            "run",
        ),
    ],
)
async def test_children_cannot_reference_foreign_parent_ids(app_engine, make_tenant, sql, params):
    """FK checks bypass RLS: composite (tenant_id, id) keys keep references in-tenant."""
    a, b = await make_tenant(), await make_tenant()
    pid_b, rid_b = await _project(app_engine, b)
    parent = pid_b if params == "project" else rid_b
    with pytest.raises(DBAPIError, match="foreign key"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(text(sql), {"i": uuid.uuid4(), "t": a.tenant_id, "p": parent})


async def test_invitations_visible_only_to_tenant_or_token_holder(app_engine, make_tenant):
    import hashlib

    a, b = await make_tenant(), await make_tenant()
    token_hash = hashlib.sha256(b"secret-token").hexdigest()
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO tenancy.invitations (id, tenant_id, email, roles, token_hash,"
                " invited_by, expires_at) VALUES (:i, :t, 'carol@x.eu', ARRAY['viewer'], :h,"
                " 'u', now() + interval '1 day')"
            ),
            {"i": uuid.uuid4(), "t": a.tenant_id, "h": token_hash},
        )

    async def visible(email: str, digest: str) -> int:
        async with platform_transaction(app_engine) as conn:
            await conn.execute(
                text(
                    "SELECT set_config('app.user_email', :e, true),"
                    " set_config('app.invite_token_hash', :h, true)"
                ),
                {"e": email, "h": digest},
            )
            return (await conn.execute(text("SELECT count(*) FROM tenancy.invitations"))).scalar()

    assert await visible("", "") == 0
    assert await visible("carol@x.eu", "") == 0  # e-mail alone is not enough
    assert await visible("eve@x.eu", token_hash) == 0  # token alone is not enough
    assert await visible("CAROL@x.eu", token_hash) == 1
    async with tenant_transaction(app_engine, b.tenant_id) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM tenancy.invitations"))).scalar() == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, b.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenancy.invitations (id, tenant_id, email, roles, token_hash,"
                    " invited_by, expires_at) VALUES (:i, :t, 'x@x.eu', ARRAY['owner'], :h,"
                    " 'u', now() + interval '1 day')"
                ),
                {"i": uuid.uuid4(), "t": a.tenant_id, "h": "b" * 64},
            )
