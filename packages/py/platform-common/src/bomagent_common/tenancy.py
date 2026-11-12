"""Tenant context propagated through every request, message and agent run.

The context is stored in a :class:`contextvars.ContextVar` so it follows asyncio tasks.
Code that touches tenant data calls :func:`require_tenant`; there is deliberately no
"all tenants" fallback - missing context is an error (ARCHITECTURE.md §5).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field

from opentelemetry import trace

ROLES: tuple[str, ...] = ("owner", "admin", "engineer", "reviewer", "viewer")


class MissingTenantContextError(RuntimeError):
    """Raised when tenant-scoped code runs without an active tenant context."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Who is acting, on behalf of which organisation, with which roles."""

    tenant_id: uuid.UUID
    actor_id: str
    actor_type: str = "user"  # user | service | api_key | system
    roles: frozenset[str] = field(default_factory=frozenset)
    request_id: str | None = None

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


_current: ContextVar[TenantContext | None] = ContextVar("bomagent_tenant", default=None)


def current_tenant() -> TenantContext | None:
    return _current.get()


def require_tenant() -> TenantContext:
    ctx = _current.get()
    if ctx is None:
        raise MissingTenantContextError("operation requires an active tenant context")
    return ctx


@contextlib.contextmanager
def tenant_scope(ctx: TenantContext) -> Iterator[TenantContext]:
    """Activate ``ctx`` for the duration of the block and tag the current span."""
    token = _current.set(ctx)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("tenant.id", str(ctx.tenant_id))
        span.set_attribute("enduser.id", ctx.actor_id)
    try:
        yield ctx
    finally:
        _current.reset(token)
