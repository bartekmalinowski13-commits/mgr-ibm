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

import ipaddress
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response

from bomagent_common.logging import get_logger
from bomagent_common.problems import ProblemError, problem_response

log = get_logger(__name__)

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
    #: only requests that carry credentials, counted when the response has this status
    #: (a token that fails verification costs the caller a token; valid traffic is free)
    failure_status: int | None = None

    def matches(self, method: str, path: str, has_credentials: bool) -> bool:
        if self.failure_status is not None and not has_credentials:
            return False
        if self.method and self.method != method:
            return False
        if self.path is not None and self.path != path:
            return False
        if self.path_prefix is not None and not path.startswith(self.path_prefix):
            return False
        return not (self.anonymous_only and has_credentials)


#: checked in order; every matching rule must allow the request
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("sso-discover", per_minute=60, burst=30, method="GET", path="/v1/sso/discover"),
    Rule("invitation-accept", per_minute=10, burst=5, method="POST", path="/v1/invitations/accept"),
    Rule("organization-create", per_minute=10, burst=5, method="POST", path="/v1/organizations"),
    Rule("me", per_minute=300, burst=100, method="GET", path="/v1/me"),
    Rule("anonymous", per_minute=120, burst=60, path_prefix="/v1/", anonymous_only=True),
    # an Authorization header must not buy unlimited token-verification attempts
    Rule("auth-failure", per_minute=60, burst=30, path_prefix="/v1/", failure_status=401),
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

    def peek(self, *, capacity: int, per_minute: int) -> bool:
        """Would a token be available now? (consumes nothing)"""
        if self._tokens is None:
            return True
        rate = per_minute / 60.0
        return min(float(capacity), self._tokens + (self._clock() - self.updated) * rate) >= 1.0

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

    def _bucket(self, ip: str, rule: Rule) -> TokenBucket:
        key = (ip, rule.name)
        bucket = self._buckets.get(key)
        if bucket is None:
            while len(self._buckets) >= self._max:
                self._buckets.popitem(last=False)  # least recently used
            bucket = self._buckets[key] = TokenBucket(self._clock)
        else:
            self._buckets.move_to_end(key)
        return bucket

    def check(self, ip: str, rule: Rule) -> Decision:
        return self._bucket(ip, rule).take(capacity=rule.burst, per_minute=rule.per_minute)

    def blocked(self, ip: str, rule: Rule) -> bool:
        return not self._bucket(ip, rule).peek(capacity=rule.burst, per_minute=rule.per_minute)


def _bucket_key(text: str) -> str | None:
    """A valid address; IPv6 is keyed on its /64 (one subscriber holds the whole prefix)."""
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address)
    return str(addr)


def client_ip(request: Request, header: str | None) -> str:
    """Address of the caller: the configured edge header, else the socket peer.

    A header value that is not a single IP address is ignored, so a garbage or oversized value
    can neither mint fresh bucket keys nor grow memory."""
    if header:
        value = request.headers.get(header, "").strip()
        if value.startswith("["):  # [2001:db8::1]:48220
            value = value[1:].split("]", 1)[0]
        elif value.count(":") == 1:  # 198.51.100.7:48220
            value = value.split(":", 1)[0]
        key = _bucket_key(value) if value and len(value) <= 64 else None
        if key:
            return key
    peer = request.client.host if request.client else ""
    return (_bucket_key(peer) or peer[:64]) if peer else "unknown"


def _too_many(request: Request, retry_after_s: int) -> Response:
    err = ProblemError(
        429,
        "Too Many Requests",
        "too many requests from this address, retry later",
        slug="rate-limited",
    )
    response = problem_response(err.problem, request)
    response.headers["Retry-After"] = str(retry_after_s)
    return response


def install_ip_limits(
    app: FastAPI,
    *,
    enabled: bool,
    header: str | None,
    rules: Sequence[Rule] = DEFAULT_RULES,
    clock: Clock = time.monotonic,
) -> IpLimiter | None:
    if not enabled:
        return None
    if not header:
        log.warning("ip_limits_without_client_ip_header", note="all callers share the peer address")
    limiter = IpLimiter(clock=clock)

    @app.middleware("http")
    async def ip_limit_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith("/v1/"):
            has_credentials = "authorization" in request.headers
            ip = client_ip(request, header)
            failure_rules = []
            for rule in rules:
                if not rule.matches(request.method, path, has_credentials):
                    continue
                if rule.failure_status is not None:
                    failure_rules.append(rule)
                    if limiter.blocked(ip, rule):
                        return _too_many(request, 1)
                    continue
                decision = limiter.check(ip, rule)
                if not decision.allowed:
                    return _too_many(request, decision.retry_after_s)
            response = await call_next(request)
            for rule in failure_rules:
                if response.status_code == rule.failure_status:
                    limiter.check(ip, rule)
            return response
        return await call_next(request)

    return limiter
