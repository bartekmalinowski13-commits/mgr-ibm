from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from bomagent_api.app import Settings, build_authenticator, build_services, create_app
from bomagent_api.auth import (
    CAN_WRITE,
    DevAuthenticator,
    OidcAuthenticator,
    Role,
    context_from_claims,
    require,
)
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

SECRET = "x" * 40


class _Key:
    def __init__(self, key) -> None:
        self.key = key


class _Jwks:
    def __init__(self, public_key) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _Key:
        return _Key(self.public_key)


def _oidc_token(private_key, **over) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://idp.example.eu",
        "aud": "bomagent",
        "sub": "u-1",
        "iat": now,
        "exp": now + 300,
        "org_id": str(uuid.uuid4()),
        "roles": ["engineer", "unknown-role"],
    } | over
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_oidc_authenticator_validates_signature_issuer_audience_and_claims():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = OidcAuthenticator("https://idp.example.eu", "bomagent", "https://idp.example.eu/jwks")
    auth._jwks = _Jwks(key.public_key())
    ctx = auth.authenticate(_oidc_token(key))
    assert ctx.roles == frozenset({"engineer"})
    assert ctx.actor_id == "u-1"
    for bad in (
        _oidc_token(key, aud="other"),
        _oidc_token(key, iss="https://evil"),
        _oidc_token(key, exp=1),
    ):
        with pytest.raises(ProblemError) as exc:
            auth.authenticate(bad)
        assert exc.value.problem.status == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ProblemError):
        auth.authenticate(_oidc_token(other))
    with pytest.raises(ProblemError, match="organisation"):
        auth.authenticate(_oidc_token(key, org_id="not-a-uuid"))


def test_dev_authenticator_roundtrip_and_rejections():
    dev = DevAuthenticator(SECRET)
    tid = uuid.uuid4()
    ctx = dev.authenticate(dev.issue(tid, "alice", ["admin"]))
    assert ctx.tenant_id == tid
    assert ctx.has_role("admin")
    with pytest.raises(ProblemError):
        DevAuthenticator("y" * 40).authenticate(dev.issue(tid, "alice", ["admin"]))
    with pytest.raises(ProblemError):
        dev.authenticate(dev.issue(tid, "alice", ["admin"], ttl=-100))


def test_claims_and_roles():
    tid = uuid.uuid4()
    ctx = context_from_claims(
        {"sub": "s", "org_id": str(tid), "roles": "viewer admin"}, "org_id", "roles"
    )
    assert ctx.roles == frozenset({"viewer", "admin"})
    require(*CAN_WRITE)(ctx)
    with pytest.raises(ProblemError):
        require(Role.OWNER)(TenantContext(tid, "s", roles=frozenset({"viewer"})))


def test_settings_wiring_refuses_unsafe_configuration():
    with pytest.raises(RuntimeError, match="not allowed"):
        build_authenticator(Settings(auth_mode="dev", dev_auth_secret=SECRET, environment="prod"))
    with pytest.raises(RuntimeError, match="32"):
        build_authenticator(Settings(auth_mode="dev", dev_auth_secret="short"))
    with pytest.raises(RuntimeError, match="OIDC"):
        build_authenticator(Settings())
    assert isinstance(
        build_authenticator(Settings(auth_mode="dev", dev_auth_secret=SECRET)), DevAuthenticator
    )
    oidc = build_authenticator(Settings(oidc_issuer="i", oidc_audience="a", oidc_jwks_url="u"))
    assert isinstance(oidc, OidcAuthenticator)
    with pytest.raises(RuntimeError, match="queue"):
        build_services(Settings())
    with pytest.raises(RuntimeError, match="local models"):
        build_services(
            Settings(
                database_url="postgresql+psycopg://u:p@h/db",
                ingest_queue_url="q",
                runs_queue_url="r",
                allow_local_models=True,
                environment="staging",
            )
        )
    app = create_app(Settings(database_url="postgresql+psycopg://u:p@h/db"))
    assert not any(getattr(r, "path", "").startswith("/v1") for r in app.routes)
