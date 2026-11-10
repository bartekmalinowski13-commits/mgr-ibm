"""Shared machinery of the runtimes: model calls with budget, tracing and provenance."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from opentelemetry import trace
from pydantic import BaseModel

from bomagent_agents.contracts import Budget, RunConfig, TraceStep
from bomagent_agents.prompts import Prompt, data_block, load_prompt
from bomagent_agents.retrieval import Evidence, Retriever
from bomagent_agents.schemas import schema_of
from bomagent_bom.model import KbCitation, Provenance, ProvenanceKind, Requirements
from bomagent_llm.catalog import Catalog, ModelSpec
from bomagent_llm.chat import ChatClient, ChatRequest, Message, structured

tracer = trace.get_tracer("bomagent.agents")
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


@dataclass
class AgentContext:
    chat: ChatClient
    catalog: Catalog
    retriever: Retriever
    config: RunConfig
    requirements: Requirements
    run_id: str
    tenant_id: str = ""
    budget: Budget = field(init=False)
    trace: list[TraceStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.budget = Budget(self.config)

    @property
    def model(self) -> ModelSpec:
        return self.catalog.get(self.config.model_id)

    @property
    def fast_model(self) -> ModelSpec:
        return self.catalog.get(self.config.fast_model_id or self.config.model_id)

    async def ask(
        self,
        prompt_id: str,
        payload: dict[str, Any],
        schema: type[T],
        *,
        knowledge: Evidence | None = None,
        fast: bool = False,
    ) -> tuple[T, Prompt, ModelSpec]:
        """One structured call; document text goes into <data> blocks, never the system
        prompt (prompt-injection boundary)."""
        prompt = load_prompt(prompt_id)
        model = self.fast_model if fast else self.model
        parts = [data_block("input", json.dumps(payload, ensure_ascii=False, sort_keys=True))]
        if knowledge is not None:
            excerpts = [
                {
                    "chunk_id": str(h.chunk_id),
                    "document": h.title,
                    "page": h.page,
                    "text": h.content[:1200],
                }
                for h in knowledge.hits
                if not h.injection_suspect
            ]
            parts.append(data_block("knowledge", json.dumps(excerpts, ensure_ascii=False)))
        request = ChatRequest(
            prompt_id=prompt.id,
            prompt_version=prompt.full_version,
            model=model,
            messages=[Message("system", prompt.text), Message("user", "\n\n".join(parts))],
            schema_name=schema.__name__,
            json_schema=schema_of(schema),
            metadata={"run_id": self.run_id, "tenant_id": self.tenant_id, "prompt_id": prompt.id},
        )
        self.budget.check()
        result, usage = await structured(self.chat, request, schema)
        self.budget.charge(usage)
        return result, prompt, model

    async def step(self, node: str, fn: Callable[[], Awaitable[R]]) -> R:
        calls_before = self.budget.usage.llm_calls
        start = time.perf_counter()
        with tracer.start_as_current_span(
            f"node {node}", attributes={"bomagent.node": node, "bomagent.run_id": self.run_id}
        ):
            out = await fn()
        self.trace.append(
            TraceStep(
                node=node,
                duration_s=time.perf_counter() - start,
                llm_calls=self.budget.usage.llm_calls - calls_before,
            )
        )
        return out


def agent_provenance(
    agent: str,
    prompt: Prompt,
    model: ModelSpec,
    rationale: str = "",
    citations: list[KbCitation] | None = None,
) -> Provenance:
    return Provenance(
        kind=ProvenanceKind.AGENT,
        agent=agent,
        model_id=model.id,
        prompt_id=prompt.id,
        prompt_version=prompt.full_version,
        rationale=rationale[:2000],
        citations=citations or [],
    )
