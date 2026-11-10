"""Agents, versioned prompts and variant runtimes A (LLM-only) and B (hybrid)."""

from bomagent_agents.context import Budget, BudgetExceededError, RunConfig, TraceStep
from bomagent_agents.retrieval import Excerpt, KbRetriever, Retriever, StaticRetriever
from bomagent_agents.runtimes import (
    Dependencies,
    RunResult,
    UnknownVariantError,
    VariantRuntime,
    get_runtime,
)

__version__ = "0.1.0"
__all__ = [
    "Budget",
    "BudgetExceededError",
    "Dependencies",
    "Excerpt",
    "KbRetriever",
    "Retriever",
    "RunConfig",
    "RunResult",
    "StaticRetriever",
    "TraceStep",
    "UnknownVariantError",
    "VariantRuntime",
    "get_runtime",
]
