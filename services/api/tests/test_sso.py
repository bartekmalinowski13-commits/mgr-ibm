"""Single sign-on per organisation: domains, federation, discovery, first sign-in,
enforcement (ADR-0005)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from bomagent_api.app import Settings, create_app
from bomagent_common.storage import InMemoryObjectStore
from bomagent_testing.kb import make_kb

pytestmark = pytest.mark.integration


@pytest.fixture
def app(app_engine, platform_engine):
    return create_app(
        Settings(environment="test", auth_mode="local"),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={},
        kb=make_kb(),
    )


@pytest.fixture
def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a")


async def _token(c: httpx.AsyncClient, sub: str, email: str, provider: str | None = None):
    body = {"sub": sub, "email": email, "identity_provider": provider}
    tok = (await c.post("/v1/dev/token", json=body)).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


async def _org(c: httpx.AsyncClient, sub: str, email: str) -> dict[str, str]:
    auth = await _token(c, sub, email)
    org = await c.post("/v1/organizations", headers=auth, json={"name": sub, "slug": sub})
    assert org.status_code == 201, org.text
    return auth | {"X-Org-Id": org.json()["id"]}


async def _verified_domain(c, app, admin, domain: str) -> None:
    added = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain})
    assert added.status_code == 201, added.text
    record = added.json()
    assert record["txt_name"] == f"_bomagent-verify.{domain}"
    app.state.txt_resolver.records[record["txt_name"]] = [record["txt_value"]]
    verified = await c.post(f"/v1/sso/domains/{domain}/verify", headers=admin)
    assert verified.status_code == 200, verified.text


async def test_domain_verification_federation_and_discovery(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"medtech-{s}.example"
    admin = await _org(c, f"sso-{s}", f"owner@{domain}")

    added = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain.upper()})
    assert added.status_code == 422  # lower-case DNS names only
    added = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain})
    assert added.json()["verified"] is False
    again = await c.post("/v1/sso/domains", headers=admin, json={"domain": domain})
    assert again.json()["txt_value"] == added.json()["txt_value"]  # idempotent
    missing = await c.post(f"/v1/sso/domains/{domain}/verify", headers=admin)
    assert missing.status_code == 422
    assert missing.json()["type"].endswith("domain-not-verified")
    app.state.txt_resolver.records[added.json()["txt_name"]] = [added.json()["txt_value"]]
    assert (await c.post(f"/v1/sso/domains/{domain}/verify", headers=admin)).json()["verified"]

    # enforcement before a connection exists is refused
    early = await c.put(
        "/v1/sso",
        headers=admin,
        json={"protocol": "saml", "metadata_url": "https://idp.example/m.xml", "enforce": True},
    )
    assert early.status_code in (200, 409)
    saml = await c.put(
        "/v1/sso",
        headers=admin,
        json={"protocol": "saml", "metadata_url": "https://idp.example/m.xml"},
    )
    assert saml.status_code == 200, saml.text
    conn = saml.json()["connection"]
    assert conn["status"] == "active"
    provider = conn["provider_name"]
    assert provider in app.state.identity_providers.providers

    found = (await c.get("/v1/sso/discover", params={"email": f"Ann@{domain.upper()}"})).json()
    assert found == {"sso": True, "provider": provider}
    other = (await c.get("/v1/sso/discover", params={"email": "x@elsewhere.example"})).json()
    assert other == {"sso": False, "provider": None}

    audit = (await c.get("/v1/audit-events", headers=admin)).json()["items"]
    actions = {e["action"] for e in audit}
    assert {"sso.domain_added", "sso.domain_verified", "sso.updated"} <= actions


async def test_first_sign_in_through_the_provider_creates_a_membership(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"clinic-{s}.example"
    admin = await _org(c, f"jit-{s}", f"owner@{domain}")
    await _verified_domain(c, app, admin, domain)
    put = await c.put(
        "/v1/sso",
        headers=admin,
        json={
            "protocol": "saml",
            "metadata_url": "https://idp.example/m.xml",
            "default_role": "engineer",
        },
    )
    provider = put.json()["connection"]["provider_name"]
    org_id = admin["X-Org-Id"]

    eng = await _token(c, f"u-{s}", f"eve@{domain}", provider)
    me = (await c.get("/v1/me", headers=eng)).json()
    assert [(m["org_id"], m["roles"]) for m in me["organizations"]] == [(org_id, ["engineer"])]
    assert (await c.get("/v1/projects", headers=eng | {"X-Org-Id": org_id})).status_code == 200

    # the provider may vouch only for its organisation's verified domains
    outsider = await _token(c, f"x-{s}", f"mallory@other-{s}.example", provider)
    assert (await c.get("/v1/me", headers=outsider)).json()["organizations"] == []
    # a password sign-in with the domain's e-mail does not join anything
    plain = await _token(c, f"p-{s}", f"paul@{domain}")
    assert (await c.get("/v1/me", headers=plain)).json()["organizations"] == []
    # another (unknown) provider name does nothing
    forged = await _token(c, f"f-{s}", f"fred@{domain}", "org-not-a-real-provider")
    assert (await c.get("/v1/me", headers=forged)).json()["organizations"] == []

    audit = (await c.get("/v1/audit-events", headers=admin)).json()["items"]
    joined = [e for e in audit if e["action"] == "member.joined_via_sso"]
    assert [e["actor_id"] for e in joined] == [f"u-{s}"]


async def test_enforcement_requires_sso_for_the_domain_but_not_for_owners(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"labs-{s}.example"
    admin = await _org(c, f"enf-{s}", f"owner@{domain}")
    org_id = admin["X-Org-Id"]
    await _verified_domain(c, app, admin, domain)
    provider = (
        await c.put(
            "/v1/sso",
            headers=admin,
            json={"protocol": "saml", "metadata_url": "https://idp.example/m.xml"},
        )
    ).json()["connection"]["provider_name"]
    via_sso = await _token(c, f"v-{s}", f"vera@{domain}", provider)
    await c.get("/v1/me", headers=via_sso)  # joins as viewer
    enforce = await c.put(
        "/v1/sso",
        headers=admin,
        json={"protocol": "saml", "metadata_url": "https://idp.example/m.xml", "enforce": True},
    )
    assert enforce.json()["connection"]["enforce"] is True

    assert (await c.get("/v1/projects", headers=via_sso | {"X-Org-Id": org_id})).status_code == 200
    password = await _token(c, f"v-{s}", f"vera@{domain}")  # same user, no federation
    blocked = await c.get("/v1/projects", headers=password | {"X-Org-Id": org_id})
    assert blocked.status_code == 403
    assert blocked.json()["type"].endswith("sso-required")
    # owners keep access with a password (break-glass when the IdP is down)
    assert (await c.get("/v1/projects", headers=admin)).status_code == 200

    # removing the last verified domain switches enforcement off
    assert (await c.delete(f"/v1/sso/domains/{domain}", headers=admin)).status_code == 204
    settings = (await c.get("/v1/sso", headers=admin)).json()
    assert settings["connection"]["enforce"] is False
    assert (await c.get("/v1/projects", headers=password | {"X-Org-Id": org_id})).status_code == 200


async def test_rules_for_admins_domains_and_providers(client, app):
    c, s = client, uuid.uuid4().hex[:6]
    domain = f"shared-{s}.example"
    a = await _org(c, f"a-{s}", f"owner@a-{s}.example")
    b = await _org(c, f"b-{s}", f"owner@b-{s}.example")
    await _verified_domain(c, app, a, domain)

    # a verified domain belongs to one organisation
    added = (await c.post("/v1/sso/domains", headers=b, json={"domain": domain})).json()
    app.state.txt_resolver.records[added["txt_name"]].append(added["txt_value"])
    taken = await c.post(f"/v1/sso/domains/{domain}/verify", headers=b)
    assert taken.status_code == 409

    # enforcement needs a working connection
    app.state.identity_providers.fail_with = "metadata could not be fetched"
    failed = await c.put(
        "/v1/sso", headers=a, json={"protocol": "saml", "metadata_url": "https://idp.example/x"}
    )
    assert failed.json()["connection"]["status"] == "failed"
    assert "metadata could not be fetched" in failed.json()["connection"]["error"]
    refused = await c.put(
        "/v1/sso",
        headers=a,
        json={"protocol": "saml", "metadata_url": "https://idp.example/x", "enforce": True},
    )
    assert refused.status_code == 409
    app.state.identity_providers.fail_with = None
    assert (await c.get("/v1/sso/discover", params={"email": f"x@{domain}"})).json()["sso"] is False

    # OIDC needs the client secret on creation; it is never returned
    no_secret = await c.put(
        "/v1/sso",
        headers=a,
        json={"protocol": "oidc", "oidc_issuer": "https://login.example", "oidc_client_id": "c"},
    )
    assert no_secret.status_code == 422
    oidc = await c.put(
        "/v1/sso",
        headers=a,
        json={
            "protocol": "oidc",
            "oidc_issuer": "https://login.example",
            "oidc_client_id": "c",
            "oidc_client_secret": "s3cr3t-value",
        },
    )
    assert oidc.status_code == 200, oidc.text
    assert "s3cr3t-value" not in oidc.text
    audit = (await c.get("/v1/audit-events", headers=a)).json()["items"]
    assert all("s3cr3t-value" not in str(e) for e in audit)

    # only owners/admins manage SSO; deleting removes the provider
    viewer = await _token(c, f"viewer-{s}", f"viewer@a-{s}.example")
    assert (await c.get("/v1/sso", headers=viewer | {"X-Org-Id": a["X-Org-Id"]})).status_code == 403
    provider = oidc.json()["connection"]["provider_name"]
    assert (await c.delete("/v1/sso", headers=a)).status_code == 204
    assert provider not in app.state.identity_providers.providers
    assert (await c.delete("/v1/sso", headers=a)).status_code == 404


async def test_local_dns_endpoint_is_local_only(client, app_engine, platform_engine):
    ok = await client.post("/v1/sso/dev/dns", json={"name": "_x.example", "value": "v"})
    assert ok.status_code == 204
    cloud = create_app(
        Settings(
            environment="test",
            auth_mode="oidc",
            oidc_issuer="https://i",
            oidc_jwks_url="https://i/j",
        ),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        queues={},
        kb=make_kb(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=cloud), base_url="http://a"
    ) as c:
        assert (
            await c.post("/v1/sso/dev/dns", json={"name": "a", "value": "b"})
        ).status_code == 404
