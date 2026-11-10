"""Variant runtimes behind one contract (ADR-0007)."""

from __future__ import annotations

from bomagent_agents.runtimes.base import Dependencies, RunResult, VariantRuntime
from bomagent_agents.runtimes.claude_sdk_a import ClaudeSdkVariantA
from bomagent_agents.runtimes.variant_a import VariantA
from bomagent_agents.runtimes.variant_b import VariantB


class UnknownVariantError(LookupError):
    pass


def get_runtime(name: str) -> VariantRuntime:
    """``A`` (LangGraph, 100% LLM), ``B`` (LangGraph, hybrid), ``A-sdk`` (Claude Agent SDK)."""
    key = name.strip()
    if key == "A":
        return VariantA()
    if key == "B":
        return VariantB()
    if key == "A-sdk":
        return ClaudeSdkVariantA()
    raise UnknownVariantError(f"unknown variant {name!r} (expected A, B or A-sdk)")


__all__ = [
    "ClaudeSdkVariantA",
    "Dependencies",
    "RunResult",
    "UnknownVariantError",
    "VariantA",
    "VariantB",
    "VariantRuntime",
    "get_runtime",
]
