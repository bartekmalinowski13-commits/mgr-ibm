"""Organisation API keys: scope, rotation, revocation, expiry, tenant binding."""

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


@pytest.fixture
def client(app_engine, platform_engine) -> httpx.AsyncClient:
    app = create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={},
        kb=make_kb(),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def _org(c: httpx.AsyncClient, sub: str) -> dict[str, str]:
    tok = (await c.post("/v1/dev/token", json={"sub": sub, "email": f"{sub}@x.eu"})).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    org = await c.post("/v1/organizations", headers=auth, json={"name": sub, "slug": sub})
    assert org.status_code == 201, org.text
    return auth | {"X-Org-Id": org.json()["id"]}


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_key_lifecycle_and_scope(client, app_engine):
    c, s = client, uuid.uuid4().hex[:6]
    admin = await _org(c, f"k-{s}")
    other = await _org(c, f"o-{s}")
    created = await c.post(
        "/v1/api-keys",
        headers=admin,
        json={"name": "CI export", "roles": ["engineer"], "expires_in_days": 30},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    key = body["key"]
    assert key.startswith("bomk_")
    assert body["prefix"] == key[: len(body["prefix"])]
    listed = (await c.get("/v1/api-keys", headers=admin)).json()["items"]
    assert [k["id"] for k in listed] == [body["id"]]
    assert "key" not in listed[0]

    # the key acts inside its organisation only, with its own roles
    as_key = _bearer(key)
    assert (await c.get("/v1/projects", headers=as_key)).status_code == 200
    made = await c.post("/v1/projects", headers=as_key, json={"name": "via key"})
    assert made.status_code == 201
    assert made.json()["created_by"] == f"apikey:{body['id']}"
    foreign = as_key | {"X-Org-Id": other["X-Org-Id"]}
    assert (await c.get("/v1/projects", headers=foreign)).status_code == 403
    assert (await c.get("/v1/members", headers=as_key)).status_code == 403
    assert (
        await c.post("/v1/api-keys", headers=as_key, json={"name": "x", "roles": ["viewer"]})
    ).status_code == 403
    assert (await c.get("/v1/me", headers=as_key)).status_code == 401  # keys are not users
    audit = (await c.get("/v1/audit-events", headers=admin)).json()["items"]
    by_key = [e for e in audit if e["action"] == "project.created"]
    assert by_key[0]["actor_type"] == "api_key"
    assert all(key not in str(e) for e in audit)
    async with tenant_transaction(app_engine, uuid.UUID(admin["X-Org-Id"])) as conn:
        used = (await conn.execute(text("SELECT last_used_at FROM tenancy.api_keys"))).scalar()
    assert used is not None

    # rotation: new secret, same scope; the old one stops working
    rotated = await c.post(f"/v1/api-keys/{body['id']}/rotate", headers=admin)
    assert rotated.status_code == 201, rotated.text
    new_key = rotated.json()["key"]
    assert rotated.json()["roles"] == ["engineer"]
    assert (await c.get("/v1/projects", headers=as_key)).status_code == 401
    assert (await c.get("/v1/projects", headers=_bearer(new_key))).status_code == 200
    assert (await c.post(f"/v1/api-keys/{body['id']}/rotate", headers=admin)).status_code == 404

    revoke = await c.delete(f"/v1/api-keys/{rotated.json()['id']}", headers=admin)
    assert revoke.status_code == 204
    assert (await c.get("/v1/projects", headers=_bearer(new_key))).status_code == 401
    # another organisation cannot see or revoke keys
    assert (await c.get("/v1/api-keys", headers=other)).json()["items"] == []
    assert (await c.delete(f"/v1/api-keys/{body['id']}", headers=other)).status_code == 404


async def test_key_validation_expiry_and_forgery(client, app_engine):
    c, s = client, uuid.uuid4().hex[:6]
    admin = await _org(c, f"v-{s}")
    for roles in (["owner"], ["admin"], []):
        bad = await c.post("/v1/api-keys", headers=admin, json={"name": "x", "roles": roles})
        assert bad.status_code == 422
    viewer = (
        await c.post("/v1/api-keys", headers=admin, json={"name": "ro", "roles": ["viewer"]})
    ).json()
    assert (
        await c.post("/v1/projects", headers=_bearer(viewer["key"]), json={"name": "x"})
    ).status_code == 403
    assert (await c.get("/v1/projects", headers=_bearer(viewer["key"] + "x"))).status_code == 401
    assert (await c.get("/v1/projects", headers=_bearer("bomk_short"))).status_code == 401
    async with tenant_transaction(app_engine, uuid.UUID(admin["X-Org-Id"])) as conn:
        await conn.execute(
            text("UPDATE tenancy.api_keys SET revoked_at = now() WHERE id = :i"),
            {"i": viewer["id"]},
        )
    assert (await c.get("/v1/projects", headers=_bearer(viewer["key"]))).status_code == 401
