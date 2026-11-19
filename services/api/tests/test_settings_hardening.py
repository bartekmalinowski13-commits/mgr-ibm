"""Review M-4 / M-5: deployment settings that must not mislead or leak."""

from __future__ import annotations

import pytest

from bomagent_api.app import Settings, create_app
from bomagent_api.sso import Connection, InMemoryIdentityProviders

OIDC = {
    "auth_mode": "oidc",
    "oidc_issuer": "https://idp.example.eu",
    "oidc_jwks_url": "https://idp.example.eu/jwks",
    "client_ip_header": "Fly-Client-IP",
}


def test_secret_settings_are_not_in_the_repr() -> None:
    s = Settings(
        environment="test",
        auth_mode="local",
        oidc_userinfo_apikey="userinfo-secret-value",
        llm_gateway_key="sk-gateway-secret-value",
        smtp_password="smtp-secret-value",
    )
    shown = repr(s) + str(s)
    for secret in ("userinfo-secret-value", "sk-gateway-secret-value", "smtp-secret-value"):
        assert secret not in shown


async def test_hosted_deployment_without_cognito_never_reports_sso_active() -> None:
    """Without an identity broker nothing is federated: applying a connection must fail
    (stored as ``status='failed'`` with a reason), never pretend to succeed."""
    app = create_app(Settings(environment="dev", allow_fake_llm=True, **OIDC))
    with pytest.raises(RuntimeError, match="not available"):
        await app.state.identity_providers.apply(
            Connection(protocol="oidc", provider_name="t-x", oidc_issuer="https://i.example"),
            "secret",
        )


async def test_local_and_test_keep_the_in_memory_broker() -> None:
    app = create_app(Settings(environment="test", auth_mode="local"))
    providers = app.state.identity_providers
    assert isinstance(providers, InMemoryIdentityProviders)
    await providers.apply(Connection(protocol="oidc", provider_name="t-y"), None)
    assert "t-y" in providers.providers
