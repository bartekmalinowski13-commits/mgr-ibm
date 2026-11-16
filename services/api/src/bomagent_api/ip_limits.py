"""Per-IP abuse protection for routes that run before the organisation context (audit SEC-03).

``_rate_limit`` (plans.py) meters authenticated requests per user and organisation; it needs a
tenant. Everything before that point - SSO discovery, creating an organisation, accepting an
invitation, ``/v1/me`` and any request without credentials - is bounded here by token buckets
keyed on the client address.

The address comes from one configured edge header (``Fly-Client-IP`` on Fly,
``CloudFront-Viewer-Address`` behind CloudFront) and otherwise from the socket peer.
``X-Forwarded-For`` is never used: its leftmost entries are client-controlled.

State is in memory, so each replica enforces its own budget (effective limit = rule x replicas).
That is deliberate for the pilot: a shared store would need a table outside the tenant RLS
model. When the API scales out (ARCH-03) the same ``IpLimiter`` interface gets a Redis backend.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response

from bomagent_common.problems import ProblemError, problem_response

Clock = Callable[[], float]


@dataclass(frozen=True)
class Rule:
    name: str
    per_minute: int  # sustained rate
    burst: int  # bucket capacity
    method: str | None = None  # None = any method
    path: str | None = None  # exact path
    path_prefix: str | None = None
    anonymous_only: bool = False  # only requests without an Authorization header

    def matches(self, method: str, path: str, has_credentials: bool) -> bool:
        if self.method and self.method != method:
            return False
        if self.path is not None and self.path != path:
            return False
        if self.path_prefix is not None and not path.startswith(self.path_prefix):
            return False
        return not (self.anonymous_only and has_credentials)


#: checked in order; every matching rule must allow the request
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("sso-discover", per_minute=20, burst=10, method="GET", path="/v1/sso/discover"),
    Rule("invitation-accept", per_minute=10, burst=5, method="POST", path="/v1/invitations/accept"),
    Rule("organization-create", per_minute=5, burst=3, method="POST", path="/v1/organizations"),
    Rule("me", per_minute=300, burst=100, method="GET", path="/v1/me"),
    Rule("anonymous", per_minute=120, burst=60, path_prefix="/v1/", anonymous_only=True),
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_s: int = 0


class TokenBucket:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._tokens: float | None = None
        self.updated = clock()

    def take(self, *, capacity: int, per_minute: int) -> Decision:
        now = self._clock()
        rate = per_minute / 60.0
        tokens = float(capacity) if self._tokens is None else self._tokens
        tokens = min(float(capacity), tokens + (now - self.updated) * rate)
        self.updated = now
        if tokens >= 1.0:
            self._tokens = tokens - 1.0
            return Decision(True)
        self._tokens = tokens
        return Decision(False, max(1, math.ceil((1.0 - tokens) / rate)))


class IpLimiter:
    """Buckets per (address, rule); memory is bounded (oldest idle entries go first)."""

    def __init__(self, *, clock: Clock = time.monotonic, max_keys: int = 50_000) -> None:
        self._clock = clock
        self._max = max_keys
        self._buckets: OrderedDict[tuple[str, str], TokenBucket] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def check(self, ip: str, rule: Rule) -> Decision:
        key = (ip, rule.name)
        bucket = self._buckets.get(key)
        if bucket is None:
            while len(self._buckets) >= self._max:
                self._buckets.popitem(last=False)
            bucket = self._buckets[key] = TokenBucket(self._clock)
        else:
            self._buckets.move_to_end(key)
        return bucket.take(capacity=rule.burst, per_minute=rule.per_minute)


def client_ip(request: Request, header: str | None) -> str:
    """Address of the caller: the configured edge header, else the socket peer."""
    if header:
        value = request.headers.get(header, "").strip()
        if value:
            if value.startswith("["):  # [2001:db8::1]:48220
                return value[1:].split("]", 1)[0]
            if value.count(":") == 1:  # 198.51.100.7:48220
                return value.split(":", 1)[0]
            return value
    return request.client.host if request.client else "unknown"


def install_ip_limits(
    app: FastAPI,
    *,
    enabled: bool,
    header: str | None,
    rules: tuple[Rule, ...] = DEFAULT_RULES,
    clock: Clock = time.monotonic,
) -> IpLimiter | None:
    if not enabled:
        return None
    limiter = IpLimiter(clock=clock)

    @app.middleware("http")
    async def ip_limit_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith("/v1/"):
            has_credentials = "authorization" in request.headers
            ip = client_ip(request, header)
            for rule in rules:
                if not rule.matches(request.method, path, has_credentials):
                    continue
                decision = limiter.check(ip, rule)
                if not decision.allowed:
                    err = ProblemError(
                        429,
                        "Too Many Requests",
                        "too many requests from this address, retry later",
                        slug="rate-limited",
                    )
                    response = problem_response(err.problem, request)
                    response.headers["Retry-After"] = str(decision.retry_after_s)
                    return response
        return await call_next(request)

    return limiter
