"""Build runtimes and their context from configuration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from bomagent_agents.contracts import RunInput, TraceStep, VariantRuntime
from bomagent_agents.retrieval import Retriever
from bomagent_agents.runtime_base import AgentContext
from bomagent_agents.variant_a import LangGraphVariantA
from bomagent_agents.variant_b import LangGraphVariantB
from bomagent_bom.model import ParsedDesign, Usage
from bomagent_llm.catalog import Catalog, load_catalog
from bomagent_llm.chat import ChatClient

RUNTIMES = ("langgraph_a", "langgraph_b", "claude_agent_sdk_a")


def design_mpns(design: ParsedDesign) -> set[str]:
    """MPNs read from the design files (trusted by the evidence-only guard). One helper for
    the guard and the experiment's residual metric, so both read the same fields."""
    return {
        c.field("MPN", "Manufacturer Part Number").strip().upper() for c in design.components
    } - {""}


def context_factory(
    chat: ChatClient,
    retriever: Retriever,
    catalog: Catalog | None = None,
    tenant_id: str = "",
    on_step: Callable[[TraceStep, Usage], Awaitable[None]] | None = None,
    checkpointer: Callable[[RunInput], Any] | None = None,
    state_store: Callable[[RunInput], Any] | None = None,
    resume: bool = False,
    resume_attempt: int = 1,
) -> Callable[[RunInput], AgentContext]:
    cat = catalog or load_catalog()

    def make(run: RunInput) -> AgentContext:
        return AgentContext(
            design_mpns=design_mpns(run.design),
            chat=chat,
            catalog=cat,
            retriever=retriever,
            config=run.config,
            requirements=run.requirements,
            run_id=str(run.run_id),
            tenant_id=tenant_id,
            on_step=on_step,
            checkpointer=checkpointer(run) if checkpointer else None,
            state_store=state_store(run) if state_store else None,
            resume=resume,
            resume_attempt=resume_attempt,
        )

    return make


def runtime_for(
    variant: str, factory: Callable[[RunInput], AgentContext], *, runtime: str | None = None
) -> VariantRuntime:
    name = runtime or ("langgraph_a" if variant == "A" else "langgraph_b")
    if name == "langgraph_a":
        return LangGraphVariantA(factory)
    if name == "langgraph_b":
        return LangGraphVariantB(factory)
    if name == "claude_agent_sdk_a":
        from bomagent_agents.claude_sdk_a import ClaudeAgentSdkVariantA

        return ClaudeAgentSdkVariantA(factory)
    raise ValueError(f"unknown runtime {name!r}; one of {RUNTIMES}")
