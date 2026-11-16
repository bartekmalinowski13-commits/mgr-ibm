"""SEC-11: Swagger UI and the OpenAPI document are only served in local/test/dev."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bomagent_api.app import Settings, create_app


@pytest.mark.parametrize(
    ("environment", "expected"),
    [("local", True), ("test", True), ("dev", True), ("staging", False), ("prod", False)],
)
def test_docs_enabled_follows_the_environment(environment, expected):
    assert Settings(environment=environment).docs_enabled is expected


def test_docs_and_openapi_are_not_served_in_production():
    settings = Settings(
        environment="prod",
        auth_mode="oidc",
        oidc_issuer="https://idp.example.eu",
        oidc_jwks_url="https://idp.example.eu/jwks",
        client_ip_header="Fly-Client-IP",
        allow_fake_llm=True,  # the embeddings policy is tested in test_embeddings_policy.py
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/healthz").status_code == 200


def test_docs_are_served_in_test_environments():
    with TestClient(create_app(Settings(environment="test", auth_mode="local"))) as client:
        assert client.get("/openapi.json").status_code == 200
