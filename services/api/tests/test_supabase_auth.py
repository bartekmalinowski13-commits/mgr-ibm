"""Supabase Auth access tokens (Supabase pilot): JWKS with asymmetric keys, claims in
``user_metadata`` configured as dotted paths. Keys are generated locally (no network)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from pydantic import ValidationError

from bomagent_api.app import Settings, create_app
from bomagent_api.auth import TokenVerifier, claim
from bomagent_common.problems import ProblemError

REF = "abcdefghijklmnop"
ISSUER = f"https://{REF}.supabase.co/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
SUPABASE = {
    "oidc_issuer": ISSUER,
    "oidc_audience": "authenticated",
    "oidc_jwks_url": JWKS_URL,
    "oidc_algorithms": ["ES256", "RS256"],
    "oidc_email_verified_claim": "user_metadata.email_verified",
    "oidc_name_claims": ["user_metadata.full_name", "user_metadata.name"],
}


class Keys:
    def __init__(self) -> None:
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ec_jwk = json.loads(ECAlgorithm.to_jwk(self.ec.public_key()))
        rsa_jwk = json.loads(RSAAlgorithm.to_jwk(self.rsa.public_key()))
        self.jwks = {
            "keys": [
                ec_jwk | {"kid": "ec-1", "alg": "ES256", "use": "sig"},
                rsa_jwk | {"kid": "rsa-1", "alg": "RS256", "use": "sig"},
            ]
        }

    def token(self, alg: str = "ES256", **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": str(uuid.UUID(int=7)),
            "email": "anna@medtech.example",
            "role": "authenticated",
            "user_metadata": {"email_verified": True, "full_name": "Anna Nowak"},
            "app_metadata": {"provider": "email"},
            "iat": now,
            "exp": now + 600,
        } | overrides
        key, kid = (self.ec, "ec-1") if alg.startswith("ES") else (self.rsa, "rsa-1")
        return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture(scope="module")
def keys() -> Keys:
    return Keys()


def _verifier(keys: Keys, **settings: Any) -> TokenVerifier:
    s = Settings(environment="test", **(SUPABASE | settings))
    verifier = TokenVerifier.from_settings(s)
    assert verifier._jwk_client is not None
    verifier._jwk_client.fetch_data = lambda: keys.jwks  # type: ignore[method-assign]
    return verifier


def test_claim_resolves_dotted_paths():
    claims = {"email": "a@x.eu", "user_metadata": {"name": "A", "nested": {"x": 1}}}
    assert claim(claims, "email") == "a@x.eu"
    assert claim(claims, "user_metadata.name") == "A"
    assert claim(claims, "user_metadata.nested.x") == 1
    assert claim(claims, "user_metadata.missing") is None
    assert claim(claims, "email.deeper") is None


def test_supabase_es256_token(keys):
    principal = _verifier(keys).verify(keys.token())
    assert principal.sub == str(uuid.UUID(int=7))
    assert principal.email == "anna@medtech.example"
    assert principal.name == "Anna Nowak"
    assert principal.email_verified is True
    assert principal.identity_provider is None


def test_supabase_rs256_token_and_name_fallback(keys):
    token = keys.token("RS256", user_metadata={"email_verified": True, "name": "Anna"})
    assert _verifier(keys).verify(token).name == "Anna"


def test_unverified_email_is_not_trusted(keys):
    for meta in ({"email_verified": False}, {}, {"email_verified": "yes"}):
        assert _verifier(keys).verify(keys.token(user_metadata=meta)).email_verified is False
    # a top-level claim is ignored when the setting points into user_metadata
    token = keys.token(user_metadata={}, email_verified=True)
    assert _verifier(keys).verify(token).email_verified is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},
        {"iss": "https://other.supabase.co/auth/v1"},
        {"exp": int(time.time()) - 10},
    ],
    ids=["audience", "issuer", "expired"],
)
def test_wrong_audience_issuer_or_expiry_is_rejected(keys, overrides):
    with pytest.raises(ProblemError) as err:
        _verifier(keys).verify(keys.token(**overrides))
    assert err.value.problem.status == 401


def test_hs256_with_a_shared_secret_is_rejected(keys):
    """Supabase's legacy JWT secret (HS256) must never be accepted, even with a kid of a
    published key."""
    now = int(time.time())
    forged = jwt.encode(
        {"iss": ISSUER, "aud": "authenticated", "sub": "x", "exp": now + 60},
        "super-secret-jwt-token-with-at-least-32-characters-long",
        algorithm="HS256",
        headers={"kid": "ec-1"},
    )
    with pytest.raises(ProblemError):
        _verifier(keys).verify(forged)


def test_algorithm_not_in_the_allowed_list_is_rejected(keys):
    with pytest.raises(ProblemError):
        _verifier(keys, oidc_algorithms=["RS256"]).verify(keys.token("ES256"))


@pytest.mark.parametrize("alg", ["HS256", "HS512", "none", "XX1"])
def test_symmetric_or_unknown_algorithms_are_refused_in_settings(alg):
    with pytest.raises(ValidationError, match="asymmetric"):
        Settings(environment="test", oidc_algorithms=[alg])


def test_defaults_keep_cognito_behaviour():
    s = Settings(environment="test")
    assert s.oidc_algorithms == ["RS256"]
    assert s.oidc_email_claim == "email"
    assert s.oidc_email_verified_claim == "email_verified"
    assert s.oidc_name_claims == ["name"]


def test_settings_parse_from_the_environment(monkeypatch):
    monkeypatch.setenv("BOMAGENT_OIDC_ALGORITHMS", '["ES256","RS256"]')
    monkeypatch.setenv("BOMAGENT_OIDC_NAME_CLAIMS", '["user_metadata.full_name"]')
    monkeypatch.setenv("BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM", "user_metadata.email_verified")
    s = Settings(environment="test")
    assert s.oidc_algorithms == ["ES256", "RS256"]
    assert s.oidc_name_claims == ["user_metadata.full_name"]
    assert s.oidc_email_verified_claim == "user_metadata.email_verified"


@pytest.mark.integration
async def test_supabase_user_onboards_through_the_api(keys, app_engine, platform_engine):
    from bomagent_common.storage import InMemoryObjectStore
    from bomagent_testing.kb import make_kb

    app = create_app(
        Settings(environment="test", auth_mode="oidc", **SUPABASE),
        engine=app_engine,
        platform_engine=platform_engine,
        store=InMemoryObjectStore(enforce_tenant=False),
        kb=make_kb(),
    )
    app.state.verifier._jwk_client.fetch_data = lambda: keys.jwks
    sub = str(uuid.uuid4())
    slug = f"supa-{sub[:8]}"
    auth = {"Authorization": f"Bearer {keys.token(sub=sub)}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        org = await client.post(
            "/v1/organizations", headers=auth, json={"name": slug, "slug": slug}
        )
        assert org.status_code == 201, org.text
        me = (await client.get("/v1/me", headers=auth)).json()
        unverified = {
            "Authorization": "Bearer "
            + keys.token(sub=str(uuid.uuid4()), user_metadata={"email_verified": False})
        }
        refused = await client.post(
            "/v1/organizations", headers=unverified, json={"name": "x", "slug": f"{slug}-x"}
        )
    assert [o["slug"] for o in me["organizations"]] == [slug]
    assert refused.status_code == 403
