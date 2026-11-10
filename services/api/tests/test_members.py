"""Organisation members and invitations (local mock IdP, real PostgreSQL)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from bomagent_api.app import Settings, create_app
from bomagent_common.db import tenant_transaction
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


class Env:
    def __init__(self, app_engine, platform_engine) -> None:
        self.app = create_app(
            Settings(environment="test", auth_mode="local"),
            engine=app_engine,
            platform_engine=platform_engine,
            store=InMemoryObjectStore(enforce_tenant=False),
            queues={},
            kb=make_kb(),
        )
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://a")
        self.platform_engine = platform_engine

    async def login(self, sub: str, email: str | None = None, verified: bool = True) -> dict:
        resp = await self.c.post(
            "/v1/dev/token",
            json={"sub": sub, "email": email or f"{sub}@x.eu", "email_verified": verified},
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def org(self, auth: dict, slug: str) -> dict:
        resp = await self.c.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert resp.status_code == 201, resp.text
        return auth | {"X-Org-Id": resp.json()["id"]}

    async def invite(self, admin: dict, email: str, roles: list[str]) -> httpx.Response:
        return await self.c.post(
            "/v1/invitations", headers=admin, json={"email": email, "roles": roles}
        )

    async def join(self, admin: dict, sub: str, roles: list[str]) -> dict:
        resp = await self.invite(admin, f"{sub}@x.eu", roles)
        assert resp.status_code == 201, resp.text
        user = await self.login(sub)
        ok = await self.c.post(
            "/v1/invitations/accept", headers=user, json={"token": resp.json()["token"]}
        )
        assert ok.status_code == 200, ok.text
        return user | {"X-Org-Id": admin["X-Org-Id"]}


@pytest.fixture
def env(app_engine, platform_engine) -> Env:
    return Env(app_engine, platform_engine)


async def test_invite_accept_and_member_listing(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"m-{s}")
    resp = await env.invite(owner, f"Bob-{s}@X.eu", ["engineer"])
    assert resp.status_code == 201, resp.text
    inv = resp.json()
    assert inv["email"] == f"bob-{s}@x.eu"
    assert inv["status"] == "pending"
    assert inv["token"]

    listed = (await env.c.get("/v1/invitations", headers=owner)).json()
    assert [i["id"] for i in listed["items"]] == [inv["id"]]
    assert "token" not in listed["items"][0]  # the secret is shown once, never listed

    dup = await env.invite(owner, f"bob-{s}@x.eu", ["viewer"])
    assert dup.status_code == 409

    # wrong e-mail, unverified e-mail, wrong token: all look like "no such invitation"
    eve = await env.login(f"eve-{s}")
    assert (
        await env.c.post("/v1/invitations/accept", headers=eve, json={"token": inv["token"]})
    ).status_code == 404
    unverified = await env.login(f"bob-{s}", f"bob-{s}@x.eu", verified=False)
    assert (
        await env.c.post("/v1/invitations/accept", headers=unverified, json={"token": inv["token"]})
    ).status_code == 403
    bob = await env.login(f"bob-{s}", f"bob-{s}@x.eu")
    forged = inv["token"][:-4] + "AAAA"
    assert (
        await env.c.post("/v1/invitations/accept", headers=bob, json={"token": forged})
    ).status_code == 404

    ok = await env.c.post("/v1/invitations/accept", headers=bob, json={"token": inv["token"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["org_id"] == owner["X-Org-Id"]
    assert ok.json()["roles"] == ["engineer"]
    again = await env.c.post("/v1/invitations/accept", headers=bob, json={"token": inv["token"]})
    assert again.status_code == 404

    me = (await env.c.get("/v1/me", headers=bob)).json()
    assert [o["roles"] for o in me["organizations"]] == [["engineer"]]
    members = (await env.c.get("/v1/members", headers=owner)).json()
    assert {(m["user_sub"], tuple(m["roles"])) for m in members["items"]} == {
        (f"own-{s}", ("owner",)),
        (f"bob-{s}", ("engineer",)),
    }
    bob_org = bob | {"X-Org-Id": owner["X-Org-Id"]}
    assert (await env.c.get("/v1/members", headers=bob_org)).status_code == 403
    assert (await env.invite(bob_org, f"x-{s}@x.eu", ["viewer"])).status_code == 403
    assert (await env.c.get("/v1/projects", headers=bob_org)).status_code == 200

    events = (await env.c.get("/v1/audit-events", headers=owner)).json()["items"]
    actions = [e["action"] for e in events]
    assert "member.invited" in actions
    assert "member.joined" in actions
    assert all(inv["token"] not in str(e) for e in events)


async def test_role_changes_and_owner_protection(env):
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"own-{s}"), f"r-{s}")
    admin = await env.join(owner, f"adm-{s}", ["admin"])
    eng = await env.join(owner, f"eng-{s}", ["engineer"])

    # only owners grant or invite owners
    assert (await env.invite(admin, f"o2-{s}@x.eu", ["owner"])).status_code == 403
    assert (
        await env.c.patch(f"/v1/members/eng-{s}", headers=admin, json={"roles": ["owner"]})
    ).status_code == 403
    # admins cannot change owners
    assert (
        await env.c.patch(f"/v1/members/own-{s}", headers=admin, json={"roles": ["viewer"]})
    ).status_code == 403
    changed = await env.c.patch(f"/v1/members/eng-{s}", headers=admin, json={"roles": ["reviewer"]})
    assert changed.status_code == 200
    assert changed.json()["roles"] == ["reviewer"]
    assert (await env.c.post("/v1/projects", headers=eng, json={"name": "x"})).status_code == 403

    # the last owner can be neither demoted nor removed
    assert (
        await env.c.patch(f"/v1/members/own-{s}", headers=owner, json={"roles": ["admin"]})
    ).status_code == 409
    assert (await env.c.delete(f"/v1/members/own-{s}", headers=owner)).status_code == 409
    assert (
        await env.c.patch(f"/v1/members/adm-{s}", headers=owner, json={"roles": ["owner"]})
    ).status_code == 200
    assert (
        await env.c.patch(f"/v1/members/own-{s}", headers=owner, json={"roles": ["admin"]})
    ).status_code == 200

    assert (await env.c.delete(f"/v1/members/eng-{s}", headers=admin)).status_code == 204
    assert (await env.c.get("/v1/projects", headers=eng)).status_code == 403
    assert (await env.c.delete(f"/v1/members/eng-{s}", headers=admin)).status_code == 404
    assert (
        await env.c.patch("/v1/members/nobody", headers=admin, json={"roles": ["viewer"]})
    ).status_code == 404
    bad = await env.c.patch(f"/v1/members/adm-{s}", headers=admin, json={"roles": ["root"]})
    assert bad.status_code == 422


async def test_revoke_expiry_and_tenant_boundaries(env):
    s = uuid.uuid4().hex[:6]
    a = await env.org(await env.login(f"a-{s}"), f"ia-{s}")
    b = await env.org(await env.login(f"b-{s}"), f"ib-{s}")
    inv = (await env.invite(a, f"c-{s}@x.eu", ["viewer"])).json()

    # another organisation neither sees nor revokes it
    assert (await env.c.get("/v1/invitations", headers=b)).json()["items"] == []
    assert (await env.c.delete(f"/v1/invitations/{inv['id']}", headers=b)).status_code == 404
    assert (await env.c.delete(f"/v1/members/a-{s}", headers=b)).status_code == 404

    assert (await env.c.delete(f"/v1/invitations/{inv['id']}", headers=a)).status_code == 204
    carol = await env.login(f"c-{s}")
    assert (
        await env.c.post("/v1/invitations/accept", headers=carol, json={"token": inv["token"]})
    ).status_code == 404

    expired = (await env.invite(a, f"c-{s}@x.eu", ["viewer"])).json()
    async with tenant_transaction(env.app.state.engine, uuid.UUID(a["X-Org-Id"])) as conn:
        await conn.execute(
            text(
                "UPDATE tenancy.invitations SET expires_at = now() - interval '1 second'"
                " WHERE id = :i"
            ),
            {"i": expired["id"]},
        )
    assert (
        await env.c.post("/v1/invitations/accept", headers=carol, json={"token": expired["token"]})
    ).status_code == 404
    assert (
        await env.c.post("/v1/invitations/accept", headers=carol, json={"token": "x" * 200})
    ).status_code in (404, 422)


# --------------------------------------------------------------------------- hardening
async def test_onboarding_needs_verified_email_and_is_audited(env):
    s = uuid.uuid4().hex[:6]
    unverified = await env.login(f"u-{s}", verified=False)
    resp = await env.c.post(
        "/v1/organizations", headers=unverified, json={"name": "x", "slug": f"u-{s}"}
    )
    assert resp.status_code == 403
    owner = await env.org(await env.login(f"o-{s}"), f"o-{s}")
    events = (await env.c.get("/v1/audit-events", headers=owner)).json()["items"]
    assert [e["action"] for e in events] == ["org.created"]


def test_oidc_settings_are_required_outside_local():
    with pytest.raises(RuntimeError, match="OIDC"):
        create_app(Settings(environment="prod", auth_mode="oidc"))


async def test_upload_limits_and_replacement(env):
    from bomagent_common.messaging import InMemoryQueue

    env.app.state.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"o-{s}"), f"up-{s}")
    pid = (await env.c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    url = f"/v1/projects/{pid}/files"
    huge = await env.c.post(
        url, headers=owner | {"Content-Length": str(200 * 1024 * 1024)}, content=b"x"
    )
    assert huge.status_code == 413
    assert huge.headers["content-type"].startswith("application/problem+json")

    async def chunks():
        yield b"--b\r\n"

    chunked = await env.c.post(
        url, headers=owner | {"Content-Type": "multipart/form-data; boundary=b"}, content=chunks()
    )
    assert chunked.status_code == 411

    store = env.app.state.store
    for body in (b"first", b"second"):
        resp = await env.c.post(
            url, headers=owner, files={"file": ("a.kicad_sch", body, "text/html")}
        )
        assert resp.status_code == 201, resp.text
    kept = [k for k in store.objects if k.endswith("/a.kicad_sch")]
    assert [store.objects[k] for k in kept] == [b"second"]  # the replaced object is deleted


async def test_event_stream_ends_when_membership_is_removed(env, monkeypatch):
    import asyncio

    from bomagent_api.routers import runs
    from bomagent_common.messaging import InMemoryQueue

    monkeypatch.setattr(runs, "SSE_RECHECK_S", 0.02)
    env.app.state.queues = {"ingest": InMemoryQueue(), "runs": InMemoryQueue()}
    env.app.state.sse_interval_s = 0.01
    env.app.state.sse_timeout_s = 10
    s = uuid.uuid4().hex[:6]
    owner = await env.org(await env.login(f"o-{s}"), f"sse-{s}")
    viewer = await env.join(owner, f"v-{s}", ["viewer"])
    pid = (await env.c.post("/v1/projects", headers=owner, json={"name": "p"})).json()["id"]
    await env.c.post(
        f"/v1/projects/{pid}/files", headers=owner, files={"file": ("a.kicad_sch", b"x")}
    )
    run_id = (
        await env.c.post("/v1/runs", headers=owner, json={"project_id": pid, "variant": "B"})
    ).json()["id"]  # stays queued: no worker runs

    stream = asyncio.create_task(env.c.get(f"/v1/runs/{run_id}/events", headers=viewer))
    await asyncio.sleep(0.1)
    assert (await env.c.delete(f"/v1/members/v-{s}", headers=owner)).status_code == 204
    resp = await asyncio.wait_for(stream, timeout=5)
    assert resp.text.rstrip().endswith('data: {"status": "forbidden"}')
