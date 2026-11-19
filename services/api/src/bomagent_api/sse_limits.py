"""Cap on concurrently open Server-Sent Event streams (review M-3).

Every open run-progress stream polls the database about once per second for up to
``sse_timeout_s``, on the connection pool all tenants share. The per-user rate limit only
counts the opening request, so without a cap one user could hold hundreds of streams.
The counter lives in the API process: each instance has its own pool, so a per-process cap
is what protects that pool.
"""

from __future__ import annotations

import uuid
import weakref
from collections import Counter

from bomagent_common.problems import ProblemError

#: a user rarely watches more than a couple of runs; several browser tabs fit
MAX_STREAMS_PER_ACTOR = 5
#: a whole organisation, so one tenant cannot take the shared pool
MAX_STREAMS_PER_TENANT = 25
RETRY_AFTER_S = 5


class StreamSlot:
    """One open stream; :meth:`release` is idempotent."""

    def __init__(self, limiter: StreamLimiter, tenant: uuid.UUID, actor: tuple[uuid.UUID, str]):
        self._limiter = limiter
        self._tenant = tenant
        self._actor = actor
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._limiter._release(self._tenant, self._actor)

    def release_with(self, owner: object) -> None:
        """Also release when ``owner`` (the stream's generator) is garbage-collected, which
        covers a response whose body was never iterated (client gone before streaming)."""
        weakref.finalize(owner, self.release)


class StreamLimiter:
    def __init__(
        self,
        *,
        per_actor: int = MAX_STREAMS_PER_ACTOR,
        per_tenant: int = MAX_STREAMS_PER_TENANT,
    ) -> None:
        self.per_actor = per_actor
        self.per_tenant = per_tenant
        self._actors: Counter[tuple[uuid.UUID, str]] = Counter()
        self._tenants: Counter[uuid.UUID] = Counter()

    def acquire(self, tenant_id: uuid.UUID, actor_id: str) -> StreamSlot:
        """Reserve a stream slot or raise a 429 ``rate-limited`` problem."""
        actor = (tenant_id, actor_id)
        if self._actors[actor] >= self.per_actor:
            raise _limited(f"at most {self.per_actor} open event streams per user")
        if self._tenants[tenant_id] >= self.per_tenant:
            raise _limited(f"at most {self.per_tenant} open event streams per organisation")
        self._actors[actor] += 1
        self._tenants[tenant_id] += 1
        return StreamSlot(self, tenant_id, actor)

    def _release(self, tenant_id: uuid.UUID, actor: tuple[uuid.UUID, str]) -> None:
        self._actors[actor] -= 1
        if self._actors[actor] <= 0:
            del self._actors[actor]
        self._tenants[tenant_id] -= 1
        if self._tenants[tenant_id] <= 0:
            del self._tenants[tenant_id]


def _limited(detail: str) -> ProblemError:
    return ProblemError(
        429,
        "Too Many Requests",
        detail,
        slug="rate-limited",
        headers={"Retry-After": str(RETRY_AFTER_S)},
    )
