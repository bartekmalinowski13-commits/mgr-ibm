"""ARCH-07: no silent fall back to non-semantic hashing embeddings outside local/test."""

from __future__ import annotations

import pytest

from bomagent_api.app import Settings, create_app

OIDC = {
    "auth_mode": "oidc",
    "oidc_issuer": "https://idp.example.eu",
    "oidc_jwks_url": "https://idp.example.eu/jwks",
    "client_ip_header": "Fly-Client-IP",
}


def test_hosted_environment_without_a_gateway_is_refused():
    with pytest.raises(RuntimeError, match="BOMAGENT_LLM_GATEWAY_URL"):
        create_app(Settings(environment="dev", **OIDC))


def test_explicit_opt_in_allows_the_fake_embeddings():
    app = create_app(Settings(environment="dev", allow_fake_llm=True, **OIDC))
    assert type(app.state.kb.embedder).__name__ == "HashingEmbeddings"


def test_local_and_test_keep_working_without_a_gateway():
    create_app(Settings(environment="test", auth_mode="local"))


def test_a_configured_gateway_needs_no_opt_in():
    settings = Settings(
        environment="dev",
        llm_gateway_url="http://litellm:4000",
        llm_gateway_key="sk-test-key",
        **OIDC,
    )
    app = create_app(settings)
    assert type(app.state.kb.embedder).__name__ == "GatewayEmbeddings"
