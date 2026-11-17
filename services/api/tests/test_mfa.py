"""SEC-06 step-up MFA: claim shapes, the authz rule and its audit event (no database)."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bomagent_api import authz
from bomagent_api.app import Settings
from bomagent_api.auth import TokenVerifier, mfa_from_claims
from bomagent_api.authz import MFA_ACTIONS, POLICIES, MfaRequiredError, require
from bomagent_common.problems import ProblemError, install_problem_handlers
from bomagent_common.tenancy import TenantContext

ISSUER, AUD = "https://idp.example", "bomagent-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
VERIFIER = TokenVerifier(ISSUER, AUD, public_key=KEY.public_key())


def token(**claims: Any) -> str:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": AUD, "sub": "u1", "iat": now, "exp": now + 600}
    return jwt.encode(base | claims, KEY, algorithm="RS256")


# --------------------------------------------------------------------------- claim shapes
@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"aal": "aal2"}, True),  # Supabase after a TOTP challenge
        ({"aal": "aal3"}, True),
        ({"aal": "aal2", "amr": [{"method": "totp", "timestamp": 1}]}, True),
        ({"amr": ["pwd", "mfa"]}, True),  # RFC 8176 (Cognito pre-token trigger)
        ({"aal": "aal1", "amr": [{"method": "password", "timestamp": 1}]}, False),
        ({"aal": "aal1"}, False),
        ({}, False),  # absent claims
        ({"aal": None, "amr": None}, False),
        # an e-mail one-time code is one factor: Supabase aal1 with amr method "otp"
        ({"aal": "aal1", "amr": [{"method": "otp", "timestamp": 1}]}, False),
        ({"amr": ["otp"]}, False),
        ({"amr": ["pwd"]}, False),
        # malformed shapes fail closed
        ({"aal": ["aal2"]}, False),
        ({"aal": 2}, False),
        ({"aal": "AAL2"}, False),
        ({"amr": "mfa"}, False),  # a string, not a list
        ({"amr": {"mfa": True}}, False),
        ({"amr": [["mfa"]]}, False),
        ({"amr": [{"method": "mfa"}]}, False),  # dict shape is never trusted on its own
        ({"amr": [None, 1, True]}, False),
    ],
)
def test_mfa_from_claims(claims, expected):
    assert mfa_from_claims(claims) is expected


def test_user_editable_metadata_is_ignored():
    forged = {
        "user_metadata": {"aal": "aal2", "amr": ["mfa"]},
        "app_metadata": {"aal": "aal2"},
    }
    assert mfa_from_claims(forged) is False
    assert VERIFIER.verify(token(**forged)).mfa is False


def test_verifier_reads_signed_claims():
    assert VERIFIER.verify(token(aal="aal2")).mfa is True
    assert VERIFIER.verify(token(amr=["mfa"])).mfa is True
    assert VERIFIER.verify(token()).mfa is False


def test_forged_aal_without_the_idp_key_is_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode(
        {"iss": ISSUER, "aud": AUD, "sub": "u1", "exp": now + 60, "aal": "aal2"},
        other,
        algorithm="RS256",
    )
    with pytest.raises(ProblemError) as err:
        VERIFIER.verify(forged)
    assert err.value.problem.status == 401


def test_unsigned_token_with_aal2_is_rejected():
    now = int(time.time())
    none_token = jwt.encode(
        {"iss": ISSUER, "aud": AUD, "sub": "u1", "exp": now + 60, "aal": "aal2"},
        None,
        algorithm="none",
    )
    with pytest.raises(ProblemError):
        VERIFIER.verify(none_token)


def test_configurable_amr_values():
    custom = TokenVerifier(ISSUER, AUD, public_key=KEY.public_key(), mfa_amr_values=["mfa", "hwk"])
    assert custom.verify(token(amr=["hwk"])).mfa is True
    assert VERIFIER.verify(token(amr=["hwk"])).mfa is False


def test_settings_default_is_off_and_amr_default():
    s = Settings(environment="test", auth_mode="local")
    assert s.mfa_enforced is False
    assert s.oidc_mfa_amr_values == ["mfa"]


# --------------------------------------------------------------------------- authz rule
def ctx(roles: set[str], mfa: bool | None) -> TenantContext:
    return TenantContext(tenant_id=uuid.uuid4(), actor_id="u1", roles=frozenset(roles), mfa=mfa)


def test_mfa_actions_are_exactly_the_audited_ones_and_exist():
    assert {
        "member.manage",
        "member.invite",
        "apikey.manage",
        "sso.manage",
        "org.update",
    } == MFA_ACTIONS
    assert POLICIES.keys() >= MFA_ACTIONS


@pytest.mark.parametrize("action", sorted(MFA_ACTIONS))
def test_enforced_without_mfa_is_refused(action):
    with pytest.raises(MfaRequiredError) as err:
        require(ctx({"owner"}, mfa=False), action)
    assert err.value.problem.status == 403
    assert err.value.problem.type.endswith("/mfa-required")
    assert "insufficient_user_authentication" in err.value.headers["WWW-Authenticate"]


@pytest.mark.parametrize("action", sorted(MFA_ACTIONS))
@pytest.mark.parametrize("mfa", [True, None])  # proven, or enforcement off / API key
def test_allowed_with_mfa_or_when_not_enforced(action, mfa):
    require(ctx({"owner"}, mfa=mfa), action)


def test_other_actions_never_need_mfa():
    for action in set(POLICIES) - MFA_ACTIONS:
        require(ctx({"owner"}, mfa=False), action)


def test_role_check_comes_first():
    with pytest.raises(ProblemError) as err:
        require(ctx({"viewer"}, mfa=False), "member.manage")
    assert not isinstance(err.value, MfaRequiredError)
    assert err.value.problem.type.endswith("/forbidden-action")


# --------------------------------------------------------------------------- handler + audit
class FakeConn:
    pass


def make_app(monkeypatch, audit_fails: bool = False) -> tuple[TestClient, list[Any]]:
    events: list[Any] = []

    class Tx:
        def __init__(self, engine, tenant_id=None):
            events.append(("tx", tenant_id))

        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    async def fake_emit(conn, event, c=None):
        if audit_fails:
            raise RuntimeError("db down")
        events.append((event.action, event.object_id, c.actor_id))

    monkeypatch.setattr(authz, "tenant_transaction", Tx)
    monkeypatch.setattr(authz, "emit_audit", fake_emit)
    app = FastAPI()
    install_problem_handlers(app)
    app.add_exception_handler(MfaRequiredError, authz.mfa_required_handler)
    app.state.engine = object()

    @app.post("/x")
    async def route() -> dict[str, str]:
        require(ctx({"owner"}, mfa=False), "apikey.manage")
        return {}

    return TestClient(app), events


def test_denial_is_a_problem_json_and_audited(monkeypatch):
    client, events = make_app(monkeypatch)
    resp = client.post("/x")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"].endswith("/mfa-required")
    assert "insufficient_user_authentication" in resp.headers["www-authenticate"]
    assert ("auth.mfa_required", "apikey.manage", "u1") in events


def test_audit_failure_keeps_the_403(monkeypatch):
    client, _ = make_app(monkeypatch, audit_fails=True)
    resp = client.post("/x")
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/mfa-required")
