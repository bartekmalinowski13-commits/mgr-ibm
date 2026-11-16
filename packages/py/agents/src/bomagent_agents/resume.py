"""Resume a crashed run from its last checkpoint (ARCH-05).

LangGraph checkpoints hold the graph state; what lives only in the process - the budget
(usage, elapsed time), the trace, MPNs seen in evidence, run findings - is saved after
every step as a *state snapshot* in a :class:`RunStateStore` and restored before
``ainvoke(None, config)`` continues the graph. A resumed run records that it was resumed
and from which checkpoint (:class:`ResumeRecord`: trace marker ``run.resumed``, audit
event, ``RunOutput.resumed``).

Reproducibility: the continuation uses the same config, prompts, retrieval snapshot and
model; spend of the interrupted steps stays in the budget (it was really spent), and a
step that was cut off is executed again and appears twice in the trace.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from bomagent_agents.contracts import ResumeRecord, TraceStep
from bomagent_bom.model import Finding, Usage

if TYPE_CHECKING:
    from bomagent_agents.runtime_base import AgentContext

RESUME_NODE = "run.resumed"


class RunStateStore(Protocol):
    """Per-run snapshot of the process-side state (tenant-scoped in the worker)."""

    async def save_state(self, run_id: uuid.UUID, state: dict[str, Any]) -> None: ...

    async def load_state(self, run_id: uuid.UUID) -> dict[str, Any] | None: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, dict[str, Any]] = {}

    async def save_state(self, run_id: uuid.UUID, state: dict[str, Any]) -> None:
        self.states[run_id] = state

    async def load_state(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        return self.states.get(run_id)


def snapshot(ctx: AgentContext) -> dict[str, Any]:
    return {
        "usage": ctx.budget.usage.model_dump(mode="json"),
        "elapsed_s": time.monotonic() - ctx.budget.started,
        "trace": [s.model_dump(mode="json") for s in ctx.trace],
        "evidence_mpns": sorted(ctx.evidence_mpns),
        "issues": [f.model_dump(mode="json") for f in ctx.issues],
        "budget_hit": ctx.budget_hit,
        "failed": ctx.failed,
    }


def restore(ctx: AgentContext, state: dict[str, Any]) -> None:
    ctx.budget.usage = Usage.model_validate(state["usage"])
    # the wall-time limit counts the time the run really worked, not the downtime
    ctx.budget.started = time.monotonic() - float(state.get("elapsed_s", 0.0))
    ctx.trace[:] = [TraceStep.model_validate(s) for s in state["trace"]]
    ctx.evidence_mpns |= set(state["evidence_mpns"])
    ctx.issues[:] = [Finding.model_validate(f) for f in state["issues"]]
    ctx.budget_hit = bool(state.get("budget_hit", False))
    ctx.failed = bool(state.get("failed", False))


async def begin(ctx: AgentContext, graph: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    """Input for ``graph.ainvoke``: ``{}`` for a new run, ``None`` to continue from the last
    checkpoint when the worker asked for a resume and one exists (state restored, the
    resume recorded in ``ctx.resumed``)."""
    if not ctx.resume or ctx.checkpointer is None:
        return {}
    snap = await graph.aget_state(config)
    checkpoint_id = (snap.config or {}).get("configurable", {}).get("checkpoint_id")
    state = await ctx.state_store.load_state(uuid.UUID(ctx.run_id)) if ctx.state_store else None
    if not checkpoint_id or state is None:
        ctx.resumed = ResumeRecord(mode="restart", attempt=ctx.resume_attempt)
        await ctx.record_resume()
        return {}  # crashed before the first checkpoint: nothing to continue from
    restore(ctx, state)
    ctx.resumed = ResumeRecord(
        mode="checkpoint",
        checkpoint_id=str(checkpoint_id),
        restored_steps=len(ctx.trace),
        restored_llm_calls=ctx.budget.usage.llm_calls,
        attempt=ctx.resume_attempt,
    )
    await ctx.record_resume()
    return None
