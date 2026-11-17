"""SEC-05 SSO hardening through the HTTP API (local mock IdP, real PostgreSQL)."""

from __future__ import annotations

import time
import uuid

import httpx
import jwt
import pytest

from bomagent_api.app import Settings, create_app
from bomagent_api.routers.sso import DISCOVERY_MIN_S
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration

SAML = {"protocol": "saml", "metadata_url": "https://idp.example/m.xml"}


def make_app(app_engine, platform_engine, **settings):
    return create_app(
        Settings(environment="test", auth_mode="local", **settings),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={},
        kb=make_kb(),
    )


@pytest.fixture
def app(app_engine, platform_engine):
    return make_app(app_engine, platform_engine)


@pytest.fixture
def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def _org(c: httpx.AsyncClient, sub: str, email: str) -> dict[str, str]:
    tok = (await c.post("/v1/dev/token", json={"sub": sub, "email": email})).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    org = await c.post("/v1/organizations", headers=auth, json={"name": sub, "slug": sub})
    assert org.status_code == 201, org.text
    return auth | {"X-Org-Id": org.json()["id"]}


async def _verified_domain(c, app, admin, domain: str) -> None:
    added = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain})
    assert added.status_code == 201, added.text
    app.state.txt_resolver.records[added.json()["txt_name"]] = [added.json()["txt_value"]]
    verified = await c.post(f"/v1/sso/domains/{domain}/verify", headers=admin)
    assert verified.status_code == 200, verified.text


def aged_token(app, sub: str, email: str, provider: str, auth_time: int | None) -> dict[str, str]:
    """A token as the IdP would sign it, with a chosen ``auth_time`` (local test key)."""
    idp = app.state.local_idp
    now = int(time.time())
    claims = {
        "iss": "https://local-idp.bomagent.invalid",
        "aud": idp.audience,
        "sub": sub,
        "email": email,
        "email_verified": True,
        "identities": [{"providerName": provider, "providerType": "SAML"}],
        "iat": now,
        "exp": now + 600,
    }
    if auth_time is not None:
        claims["auth_time"] = auth_time
    return {"Authorization": f"Bearer {jwt.encode(claims, idp._key, algorithm='RS256')}"}


async def test_provider_names_are_random_stable_and_removed_by_stored_name(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    a = await _org(c, f"ra-{s}", f"owner@ra-{s}.example")
    b = await _org(c, f"rb-{s}", f"owner@rb-{s}.example")
    first = (await c.put("/v1/sso", headers=a, json=SAML)).json()["connection"]["provider_name"]
    other = (await c.put("/v1/sso", headers=b, json=SAML)).json()["connection"]["provider_name"]
    assert first != other
    for name, org in ((first, a), (other, b)):
        assert name.startswith("org-")
        assert len(name) <= 32
        assert org["X-Org-Id"].replace("-", "")[:24] not in name
    again = (await c.put("/v1/sso", headers=a, json=SAML | {"default_role": "viewer"})).json()
    assert again["connection"]["provider_name"] == first  # an update keeps the name
    assert (await c.delete("/v1/sso", headers=a)).status_code == 204
    assert first not in app.state.identity_providers.providers
    assert other in app.state.identity_providers.providers
    assert (await c.delete("/v1/sso", headers=a)).status_code == 404


async def test_free_mail_domains_cannot_be_claimed(client):
    c, s = client, uuid.uuid4().hex[:6]
    admin = await _org(c, f"fm-{s}", f"owner@fm-{s}.example")
    for domain in ("gmail.com", "mail.outlook.com", "wp.pl"):
        added = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain})
        assert added.status_code == 422, domain
        assert added.json()["type"].endswith("/domain-not-allowed")
        verify = await c.post(f"/v1/sso/domains/{domain}/verify", headers=admin)
        assert verify.status_code == 422
        assert verify.json()["type"].endswith("/domain-not-allowed")
    assert (await c.get("/v1/sso", headers=admin)).json()["domains"] == []


async def test_discovery_is_post_with_the_domain_only(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"disc-{s}.example"
    admin = await _org(c, f"dc-{s}", f"owner@{domain}")
    await _verified_domain(c, app, admin, domain)
    put = await c.put("/v1/sso", headers=admin, json=SAML)
    provider = put.json()["connection"]["provider_name"]
    found = await c.post("/v1/sso/discover", json={"domain": f" {domain.upper()}. "})
    assert found.json() == {"sso": True, "provider": provider}
    # an e-mail address is not accepted anywhere, and the old GET (address in the URL) is gone
    assert (await c.post("/v1/sso/discover", json={"domain": f"ann@{domain}"})).status_code == 422
    assert (await c.post("/v1/sso/discover", json={"email": f"ann@{domain}"})).status_code == 422
    old = await c.get("/v1/sso/discover", params={"email": f"ann@{domain}"})
    assert old.status_code in (404, 405)
    # unknown and free-mail domains answer the same way
    for other in ("nobody.example", "gmail.com"):
        resp = await c.post("/v1/sso/discover", json={"domain": other})
        assert resp.json() == {"sso": False, "provider": None}


async def test_discovery_answers_take_a_minimum_time(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"timing-{s}.example"
    admin = await _org(c, f"tm-{s}", f"owner@{domain}")
    await _verified_domain(c, app, admin, domain)
    await c.put("/v1/sso", headers=admin, json=SAML)
    for name in (domain, "nobody.example", "gmail.com"):
        started = time.monotonic()
        await c.post("/v1/sso/discover", json={"domain": name})
        assert time.monotonic() - started >= DISCOVERY_MIN_S * 0.9


async def test_enforced_members_must_have_signed_in_recently(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"age-{s}.example"
    admin = await _org(c, f"ag-{s}", f"owner@{domain}")
    h = {"X-Org-Id": admin["X-Org-Id"]}
    await _verified_domain(c, app, admin, domain)
    provider = (await c.put("/v1/sso", headers=admin, json=SAML)).json()["connection"][
        "provider_name"
    ]
    now = int(time.time())
    fresh = aged_token(app, f"v-{s}", f"vera@{domain}", provider, now - 60)
    await c.get("/v1/me", headers=fresh)  # joins as viewer
    await c.put("/v1/sso", headers=admin, json=SAML | {"enforce": True})
    assert (await c.get("/v1/projects", headers=fresh | h)).status_code == 200
    for stale in (now - 9 * 3600, None):  # older than 8 h, or no auth_time at all
        tok = aged_token(app, f"v-{s}", f"vera@{domain}", provider, stale)
        resp = await c.get("/v1/projects", headers=tok | h)
        assert resp.status_code == 401, stale
        assert resp.json()["type"].endswith("/reauth-required")
    # owners (break-glass) are not subject to it
    old_owner = aged_token(app, f"ag-{s}", f"owner@{domain}", provider, now - 30 * 3600)
    assert (await c.get("/v1/projects", headers=old_owner | h)).status_code == 200


async def test_the_age_limit_can_be_switched_off(app_engine, platform_engine):
    s = uuid.uuid4().hex[:6]
    domain = f"off-{s}.example"
    app = make_app(app_engine, platform_engine, sso_max_auth_age_s=0)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")
    admin = await _org(c, f"of-{s}", f"owner@{domain}")
    await _verified_domain(c, app, admin, domain)
    provider = (await c.put("/v1/sso", headers=admin, json=SAML)).json()["connection"][
        "provider_name"
    ]
    tok = aged_token(app, f"v-{s}", f"vera@{domain}", provider, int(time.time()) - 99 * 3600)
    await c.get("/v1/me", headers=tok)
    await c.put("/v1/sso", headers=admin, json=SAML | {"enforce": True})
    resp = await c.get("/v1/projects", headers=tok | {"X-Org-Id": admin["X-Org-Id"]})
    assert resp.status_code == 200
