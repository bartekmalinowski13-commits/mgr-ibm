"""SEC-06 through the HTTP API (local mock IdP, real PostgreSQL): off by default, 403
``mfa-required`` when enforced and the token has no second factor."""

from __future__ import annotations

import uuid

import httpx
import pytest

from bomagent_api.app import Settings, create_app
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration

KEY = {"name": "ci", "roles": ["viewer"]}
INVITE = {"email": "n@x.eu", "roles": ["viewer"]}


def make(app_engine, platform_engine, **settings):
    app = create_app(
        Settings(environment="test", auth_mode="local", **settings),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={},
        kb=make_kb(),
    )
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def login(c: httpx.AsyncClient, sub: str, **extra) -> dict:
    resp = await c.post(
        "/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu", "email_verified": True} | extra
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def org(c: httpx.AsyncClient, auth: dict, slug: str) -> dict:
    resp = await c.post("/v1/organizations", headers=auth, json={"name": slug, "slug": slug})
    assert resp.status_code == 201, resp.text
    return {"X-Org-Id": resp.json()["id"]}


async def test_off_by_default_nothing_changes(app_engine, platform_engine):
    _, c = make(app_engine, platform_engine)
    s = uuid.uuid4().hex[:6]
    auth = await login(c, f"o-{s}")
    h = auth | await org(c, auth, f"m-{s}")
    assert (await c.post("/v1/api-keys", headers=h, json=KEY)).status_code == 201
    assert (await c.post("/v1/invitations", headers=h, json=INVITE)).status_code == 201


async def test_enforced_refuses_without_mfa_and_allows_with_it(app_engine, platform_engine):
    _, c = make(app_engine, platform_engine, mfa_enforced=True)
    s = uuid.uuid4().hex[:6]
    plain = await login(c, f"o-{s}")
    scope = await org(c, plain, f"m-{s}")  # creating an organisation is not a step-up action
    h = plain | scope
    resp = await c.post("/v1/api-keys", headers=h, json=KEY)
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/mfa-required")
    # reading and normal project work are not affected
    assert (await c.get("/v1/projects", headers=h)).status_code == 200
    members = await c.get("/v1/members", headers=h)
    assert members.status_code == 200
    sub = members.json()["items"][0]["user_sub"]
    assert (await c.post("/v1/invitations", headers=h, json=INVITE)).status_code == 403
    assert (
        await c.patch(f"/v1/members/{sub}", headers=h, json={"roles": ["owner"]})
    ).status_code == 403
    assert (await c.delete(f"/v1/members/{sub}", headers=h)).status_code == 403
    mfa = await login(c, f"o-{s}", mfa=True)  # same user, second factor proven
    assert (await c.post("/v1/api-keys", headers=mfa | scope, json=KEY)).status_code == 201


async def test_denial_is_audited_and_forged_claims_do_not_help(app_engine, platform_engine):
    app, c = make(app_engine, platform_engine, mfa_enforced=True)
    s = uuid.uuid4().hex[:6]
    plain = await login(c, f"o-{s}")
    scope = await org(c, plain, f"m-{s}")
    assert (await c.post("/v1/api-keys", headers=plain | scope, json=KEY)).status_code == 403
    # the audit log is tenant-scoped (RLS): read it through the API as the same user with MFA
    proven = await login(c, f"o-{s}", mfa=True)
    events = (await c.get("/v1/audit-events?limit=100", headers=proven | scope)).json()["items"]
    assert len([e for e in events if e["action"] == "auth.mfa_required"]) == 1
    # tokens with aal1 / an unrelated amr / user-editable metadata are still refused
    for extra in (
        {"aal": "aal1"},
        {"amr": ["pwd"]},
        {"user_metadata": {"aal": "aal2", "amr": ["mfa"]}},
    ):
        tok = app.state.local_idp.issue(f"o-{s}", f"o-{s}@x.eu", extra_claims=extra)
        resp = await c.post(
            "/v1/api-keys", headers={"Authorization": f"Bearer {tok}"} | scope, json=KEY
        )
        assert resp.status_code == 403, extra
    # RFC 8176 string amr with "mfa" is accepted
    tok = app.state.local_idp.issue(f"o-{s}", f"o-{s}@x.eu", extra_claims={"amr": ["pwd", "mfa"]})
    ok = await c.post("/v1/api-keys", headers={"Authorization": f"Bearer {tok}"} | scope, json=KEY)
    assert ok.status_code == 201


async def test_viewer_gets_forbidden_action_not_mfa(app_engine, platform_engine):
    _, c = make(app_engine, platform_engine, mfa_enforced=True)
    s = uuid.uuid4().hex[:6]
    owner = await login(c, f"o-{s}", mfa=True)
    scope = await org(c, owner, f"m-{s}")
    inv = await c.post(
        "/v1/invitations",
        headers=owner | scope,
        json={"email": f"v-{s}@x.eu", "roles": ["viewer"]},
    )
    assert inv.status_code == 201, inv.text
    viewer = await login(c, f"v-{s}")
    await c.post("/v1/invitations/accept", headers=viewer, json={"token": inv.json()["token"]})
    resp = await c.post("/v1/api-keys", headers=viewer | scope, json=KEY)
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/forbidden-action")
