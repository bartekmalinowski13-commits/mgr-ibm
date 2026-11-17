"""Per-IP abuse protection before the organisation context (audit SEC-03).

No database: a bare FastAPI app carries the middleware, a fake clock drives the buckets.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest
from fastapi import FastAPI, Request, Response

from bomagent_api.ip_limits import (
    DEFAULT_RULES,
    IpLimiter,
    Rule,
    TokenBucket,
    client_ip,
    install_ip_limits,
)
from bomagent_common.problems import install_problem_handlers


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------- token bucket


def test_bucket_allows_the_burst_then_refuses_with_a_retry_hint():
    clock = Clock()
    bucket = TokenBucket(clock)
    results = [bucket.take(capacity=3, per_minute=60) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[-1].retry_after_s == 1  # 60/min = one token per second


def test_bucket_refills_over_time_but_never_above_capacity():
    clock = Clock()
    bucket = TokenBucket(clock)
    for _ in range(3):
        bucket.take(capacity=3, per_minute=60)
    assert not bucket.take(capacity=3, per_minute=60).allowed
    clock.now += 2
    assert bucket.take(capacity=3, per_minute=60).allowed  # two tokens came back
    clock.now += 10_000
    taken = [bucket.take(capacity=3, per_minute=60).allowed for _ in range(4)]
    assert taken == [True, True, True, False]


# ---------------------------------------------------------------- limiter


def test_limiter_keeps_one_bucket_per_ip_and_rule():
    clock = Clock()
    limiter = IpLimiter(clock=clock)
    rule = Rule("discover", per_minute=2, burst=2)
    assert limiter.check("1.1.1.1", rule).allowed
    assert limiter.check("1.1.1.1", rule).allowed
    assert not limiter.check("1.1.1.1", rule).allowed
    assert limiter.check("2.2.2.2", rule).allowed  # another address is unaffected
    other = Rule("accept", per_minute=2, burst=2)
    assert limiter.check("1.1.1.1", other).allowed  # another rule is unaffected


def test_limiter_memory_is_bounded_and_idle_buckets_are_dropped():
    clock = Clock()
    limiter = IpLimiter(clock=clock, max_keys=100)
    rule = Rule("x", per_minute=60, burst=5)
    for n in range(500):
        limiter.check(f"10.0.{n // 250}.{n % 250}", rule)
        clock.now += 0.001
    assert len(limiter) <= 100
    clock.now += 3600
    limiter.check("9.9.9.9", rule)
    assert len(limiter) <= 100


# ---------------------------------------------------------------- client address


def _request(headers: dict[str, str], peer: str | None = "10.1.2.3"):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


def test_client_ip_uses_the_configured_header_and_never_x_forwarded_for():
    spoofed = {"X-Forwarded-For": "6.6.6.6", "Fly-Client-IP": "203.0.113.9"}
    assert client_ip(_request(spoofed), "Fly-Client-IP") == "203.0.113.9"
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6"}), None) == "10.1.2.3"
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6"}), "Fly-Client-IP") == "10.1.2.3"
    assert client_ip(_request({}, peer=None), None) == "unknown"


def test_client_ip_reads_the_ip_of_cloudfront_viewer_address():
    req = _request({"CloudFront-Viewer-Address": "198.51.100.7:48220"})
    assert client_ip(req, "CloudFront-Viewer-Address") == "198.51.100.7"
    v6 = _request({"CloudFront-Viewer-Address": "[2001:db8::1]:48220"})
    assert client_ip(v6, "CloudFront-Viewer-Address") == "2001:db8::"  # keyed on the /64


# ---------------------------------------------------------------- middleware


def _app(
    rules: Sequence[Rule], *, header: str | None = "Fly-Client-IP", clock=None, enabled=True
) -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    install_ip_limits(app, enabled=enabled, header=header, rules=rules, clock=clock or Clock())

    @app.post("/v1/sso/discover")
    async def discover() -> dict[str, bool]:
        return {"sso": False}

    @app.post("/v1/invitations/accept")
    async def accept() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/projects")
    async def projects() -> list[str]:
        return []

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


RULES = (
    Rule("sso-discover", per_minute=60, burst=3, method="POST", path="/v1/sso/discover"),
    Rule("invitation-accept", per_minute=60, burst=2, method="POST", path="/v1/invitations/accept"),
    Rule("anonymous", per_minute=60, burst=4, anonymous_only=True, path_prefix="/v1/"),
)


async def test_strict_rule_returns_429_problem_json_with_retry_after():
    async with _client(_app(RULES)) as c:
        h = {"Fly-Client-IP": "203.0.113.9"}
        codes = [(await c.post("/v1/sso/discover", headers=h)).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        blocked = await c.post("/v1/sso/discover", headers=h)
    assert blocked.headers["content-type"].startswith("application/problem+json")
    assert blocked.headers["retry-after"] == "1"
    body = blocked.json()
    assert body["status"] == 429
    assert body["type"].endswith("/rate-limited")


async def test_limits_are_per_address_and_xff_cannot_dodge_them():
    async with _client(_app(RULES)) as c:
        for n in range(3):
            r = await c.post(
                "/v1/sso/discover",
                headers={"Fly-Client-IP": "203.0.113.9", "X-Forwarded-For": f"9.9.9.{n}"},
            )
            assert r.status_code == 200
        dodged = await c.post(
            "/v1/sso/discover",
            headers={"Fly-Client-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4"},
        )
        assert dodged.status_code == 429
        other = await c.post("/v1/sso/discover", headers={"Fly-Client-IP": "203.0.113.10"})
        assert other.status_code == 200


async def test_method_matters_and_buckets_are_independent():
    async with _client(_app(RULES)) as c:
        h = {"Fly-Client-IP": "203.0.113.9"}
        assert [
            (await c.post("/v1/invitations/accept", headers=h)).status_code for _ in range(3)
        ] == [
            200,
            200,
            429,
        ]
        assert (await c.post("/v1/sso/discover", headers=h)).status_code == 200


async def test_anonymous_bucket_does_not_apply_to_authenticated_requests():
    async with _client(_app(RULES)) as c:
        h = {"Fly-Client-IP": "203.0.113.9"}
        anon = [(await c.get("/v1/projects", headers=h)).status_code for _ in range(5)]
        assert anon == [200, 200, 200, 200, 429]
        authed = {**h, "Authorization": "Bearer t"}
        for _ in range(10):
            assert (await c.get("/v1/projects", headers=authed)).status_code == 200


async def test_tokens_return_with_time_and_health_checks_are_never_limited():
    clock = Clock()
    async with _client(_app(RULES, clock=clock)) as c:
        h = {"Fly-Client-IP": "203.0.113.9"}
        for _ in range(3):
            await c.post("/v1/sso/discover", headers=h)
        assert (await c.post("/v1/sso/discover", headers=h)).status_code == 429
        clock.now += 1
        assert (await c.post("/v1/sso/discover", headers=h)).status_code == 200
        for _ in range(50):
            assert (await c.get("/healthz", headers=h)).status_code == 200


async def test_disabled_limiter_lets_everything_through():
    async with _client(_app(RULES, enabled=False)) as c:
        for _ in range(20):
            assert (await c.post("/v1/sso/discover")).status_code == 200


@pytest.mark.parametrize("rule", DEFAULT_RULES, ids=lambda r: r.name)
def test_default_rules_are_sane(rule: Rule):
    assert 1 <= rule.burst <= rule.per_minute
    assert rule.name
    assert rule.path or rule.path_prefix


def test_ip_limits_need_a_client_ip_header_outside_local_and_test():
    from bomagent_api.app import Settings

    h = "Fly-Client-IP"
    assert not Settings(environment="test", auth_mode="local", client_ip_header=h).ip_limits_on
    assert not Settings(environment="local", auth_mode="local", client_ip_header=h).ip_limits_on
    assert Settings(environment="dev", auth_mode="local", client_ip_header=h).ip_limits_on
    assert Settings(environment="prod", auth_mode="local", client_ip_header=h).ip_limits_on
    # no trusted edge header: the peer is a shared proxy address, so the limits stay off
    assert not Settings(environment="prod", auth_mode="local").ip_limits_on
    assert not Settings(environment="prod", auth_mode="local", ip_rate_limit=False).ip_limits_on
    assert Settings(environment="test", auth_mode="local", ip_rate_limit=True).ip_limits_on


def test_client_ip_ignores_values_that_are_not_one_address():
    for bad in ("a, b", "6.6.6.6, 7.7.7.7", "x" * 5000, "not-an-ip", "999.1.1.1"):
        assert client_ip(_request({"Fly-Client-IP": bad}), "Fly-Client-IP") == "10.1.2.3"


def test_ipv6_clients_share_a_bucket_per_64_prefix():
    a = client_ip(_request({"Fly-Client-IP": "2001:db8:1:2:aaaa::1"}), "Fly-Client-IP")
    b = client_ip(_request({"Fly-Client-IP": "2001:db8:1:2:bbbb::9"}), "Fly-Client-IP")
    c = client_ip(_request({"Fly-Client-IP": "2001:db8:1:3::1"}), "Fly-Client-IP")
    assert a == b != c


async def test_invalid_tokens_cost_the_caller_but_valid_traffic_is_free():
    failure_rule = Rule(
        "auth-failure", per_minute=60, burst=2, path_prefix="/v1/", failure_status=401
    )
    app = _app([*RULES, failure_rule])

    @app.get("/v1/secret")
    async def secret(request: Request) -> Response:
        ok = request.headers.get("authorization") == "Bearer good"
        return Response(status_code=200 if ok else 401)

    async with _client(app) as c:
        h = {"Fly-Client-IP": "203.0.113.9"}
        for _ in range(5):  # valid tokens are never counted
            assert (
                await c.get("/v1/secret", headers={**h, "Authorization": "Bearer good"})
            ).status_code == 200
        bad = {**h, "Authorization": "x"}
        assert [(await c.get("/v1/secret", headers=bad)).status_code for _ in range(3)] == [
            401,
            401,
            429,
        ]
        # the address is now refused even with a valid token, until tokens come back
        assert (
            await c.get("/v1/secret", headers={**h, "Authorization": "Bearer good"})
        ).status_code == 429
        assert (
            await c.get(
                "/v1/secret", headers={"Fly-Client-IP": "203.0.113.10", "Authorization": "x"}
            )
        ).status_code == 401


# ---------------------------------------------------------------- source address for audit (SEC-04)


def test_raw_client_ip_returns_the_full_validated_address_not_the_bucket_key():
    from bomagent_api.ip_limits import raw_client_ip

    v6 = _request({"Fly-Client-IP": "2001:db8:1:2:aaaa::1"})
    assert raw_client_ip(v6, "Fly-Client-IP") == "2001:db8:1:2:aaaa::1"  # audit keeps all of it
    assert raw_client_ip(_request({"Fly-Client-IP": "garbage"}), "Fly-Client-IP") == "10.1.2.3"
    assert raw_client_ip(_request({}, peer=None), None) is None
    # zone ids and other non-inet values never reach the audit insert
    assert raw_client_ip(_request({"Fly-Client-IP": "fe80::1%eth0"}), "Fly-Client-IP") == "10.1.2.3"
    assert raw_client_ip(_request({"X-Forwarded-For": "6.6.6.6"}), None) == "10.1.2.3"


async def test_origin_middleware_exposes_the_address_to_handlers():
    from bomagent_api.ip_limits import install_origin
    from bomagent_common.request_origin import current_source_ip

    app = FastAPI()
    install_origin(app, header="Fly-Client-IP")

    @app.get("/who")
    async def who() -> dict[str, str | None]:
        return {"ip": current_source_ip()}

    async with _client(app) as c:
        assert (await c.get("/who", headers={"Fly-Client-IP": "203.0.113.9"})).json() == {
            "ip": "203.0.113.9"
        }
        # a spoofable header the deployment does not trust is ignored
        spoof = await c.get("/who", headers={"X-Forwarded-For": "6.6.6.6"})
        assert spoof.json()["ip"] == "127.0.0.1"  # the ASGI peer, never the XFF value
    assert current_source_ip() is None  # nothing leaks out of the request
