"""API contract tests (Schemathesis on the committed OpenAPI 3.1 document).

Every operation is fuzzed with an authenticated owner of a real organisation; responses
must never be 5xx and must match the declared status codes, media types and schemas.
"""

from __future__ import annotations

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import (
    content_type_conformance,
    not_a_server_error,
    response_schema_conformance,
    status_code_conformance,
)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from bomagent_api.app import Settings, create_app

pytestmark = [pytest.mark.integration, pytest.mark.contract]


@pytest.fixture(scope="module", autouse=True)
def generous_plan():
    """The fuzzer sends hundreds of requests: lift plan limits so endpoints are exercised
    (429 itself is part of the contract and covered in test_limits)."""
    from bomagent_api import plans

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(plans.PLANS, "pilot", plans.Plan(10**9, 10**9, 10**9, 10**9, 1e12, 10**15))
        yield


@pytest.fixture(scope="module")
def api(db_urls):
    # NullPool: the ASGI test clients run the app on their own event loops
    return create_app(
        Settings(environment="test", auth_mode="local", sse_timeout_s=0.2, sse_interval_s=0.05),
        engine=create_async_engine(db_urls.app, poolclass=NullPool),
        platform_engine=create_async_engine(db_urls.platform, poolclass=NullPool),
    )


@pytest.fixture(scope="module")
def auth(api):
    with TestClient(api) as client:
        token = client.post("/v1/dev/token", json={"sub": "contract", "email": "c@x.eu"}).json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        org = client.post(
            "/v1/organizations", headers=headers, json={"name": "Contract", "slug": "contract-org"}
        ).json()
        return headers | {"X-Org-Id": org["id"]}


@pytest.fixture(scope="module")
def api_schema(api):
    return schemathesis.openapi.from_asgi("/openapi.json", api)


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
    ],
)
def test_api_conforms_to_contract(case, auth):
    if case.operation.path == "/v1/organizations":
        return  # creates tenants; covered by test_api_flow
    case.call_and_validate(
        headers=auth,
        checks=[
            not_a_server_error,
            status_code_conformance,
            content_type_conformance,
            response_schema_conformance,
        ],
    )
