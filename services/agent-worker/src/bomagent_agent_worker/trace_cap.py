"""Application-level size cap for ``runs.runs.trace`` (audit DATA-01/DATA-02).

The full trace always goes to object storage (``trace.json``). The JSONB column that the API
streams and reads is bounded: when the serialised trace exceeds ``max_bytes`` the middle is
dropped deterministically and replaced by one ``truncated`` marker step that records how many
steps were dropped. Kept steps are never modified, so audit-relevant fields stay intact, and
``run.resumed`` records (ARCH-05) are always kept even when they sit in the dropped middle.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from bomagent_agents.contracts import TraceStep
from bomagent_agents.resume import RESUME_NODE

#: 256 KiB: far above a normal run's trace, well below what makes the row hurt
DEFAULT_TRACE_MAX_BYTES = 262_144
TRUNCATED_NODE = "truncated"


def _size(step: TraceStep) -> int:
    return len(json.dumps(step.model_dump(mode="json")).encode()) + 2  # separator


def trace_size(steps: Sequence[TraceStep]) -> int:
    """Bytes of the trace as stored in ``runs.trace``."""
    return len(json.dumps([s.model_dump(mode="json") for s in steps]).encode())


def _marker(dropped: int, total: int, kept_head: int, kept_tail: int) -> TraceStep:
    return TraceStep(
        node=TRUNCATED_NODE,
        duration_s=0.0,
        detail={
            "dropped": dropped,
            "total": total,
            "kept_head": kept_head,
            "kept_tail": kept_tail,
            "reason": "trace size cap",
        },
    )


def cap_trace(steps: Sequence[TraceStep], max_bytes: int) -> list[TraceStep]:
    """Return ``steps`` unchanged if they fit, else a head + marker + tail within ``max_bytes``.

    Selection order is fixed (resume records, then first, last, second, second-to-last, ...)
    and stops at the first step that does not fit, so the result depends only on the input.
    The marker is always present when anything was dropped; if even the protected steps and
    the marker exceed the cap they are kept anyway (the cap is best effort for those).
    ``max_bytes <= 0`` disables the cap.
    """
    kept_all = list(steps)
    if max_bytes <= 0 or trace_size(kept_all) <= max_bytes:
        return kept_all
    n = len(kept_all)
    keep = {i for i, s in enumerate(kept_all) if s.node == RESUME_NODE}
    order: list[int] = []
    lo, hi = 0, n - 1
    while lo <= hi:
        order.append(lo)
        if hi != lo:
            order.append(hi)
        lo, hi = lo + 1, hi - 1
    # reserve room for the marker (its detail grows with the digits of the counts)
    used = _size(_marker(n, n, n, n)) + sum(_size(kept_all[i]) for i in keep) + 2
    for i in order:
        if i in keep:
            continue
        cost = _size(kept_all[i])
        if used + cost > max_bytes:
            break
        keep.add(i)
        used += cost
    dropped = n - len(keep)
    if dropped == 0:  # only the marker reserve pushed it over: nothing to drop
        return kept_all
    first_gap = next(i for i in range(n) if i not in keep)
    head = sum(1 for i in keep if i < first_gap)
    out: list[TraceStep] = []
    for i in range(n):
        if i == first_gap:
            out.append(_marker(dropped, n, head, len(keep) - head))
        if i in keep:
            out.append(kept_all[i])
    return out
