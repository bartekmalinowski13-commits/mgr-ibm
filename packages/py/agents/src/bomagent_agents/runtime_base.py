"""Shared machinery of the runtimes: model calls with budget, tracing and provenance."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

from opentelemetry import trace
from pydantic import BaseModel

from bomagent_agents.contracts import Budget, BudgetExceededError, RunConfig, TraceStep
from bomagent_agents.prompts import Prompt, data_block, load_prompt
from bomagent_agents.retrieval import Evidence, Retriever
from bomagent_agents.schemas import schema_of
from bomagent_bom.model import (
    BomItem,
    Finding,
    KbCitation,
    Provenance,
    ProvenanceKind,
    Requirements,
    Severity,
    Usage,
)
from bomagent_llm.catalog import Catalog, ModelSpec
from bomagent_llm.chat import ChatClient, ChatRequest, LlmError, Message, structured

tracer = trace.get_tracer("bomagent.agents")
log = logging.getLogger(__name__)
# calls made inside the current step; a ContextVar so concurrent fan-out branches
# (separate asyncio tasks) do not count each other's calls
_step_calls: ContextVar[list[int] | None] = ContextVar("bomagent_step_calls", default=None)
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
    design_mpns: set[str] = field(default_factory=set)
    budget: Budget = field(init=False)
    trace: list[TraceStep] = field(default_factory=list)
    # MPNs seen as candidates in retrieved evidence during this run (guard + metrics)
    evidence_mpns: set[str] = field(default_factory=set)
    issues: list[Finding] = field(default_factory=list)
    budget_hit: bool = False
    failed: bool = False
    #: called after every finished step with the usage so far (live progress, SSE);
    #: a failing callback is logged and never breaks the run
    on_step: Callable[[TraceStep, Usage], Awaitable[None]] | None = None

    def __post_init__(self) -> None:
        self.budget = Budget(self.config)

    @property
    def status(self) -> str:
        return "failed" if self.failed else "budget_exceeded" if self.budget_hit else "completed"

    def mpn_allowed(self, mpn: str) -> bool:
        """Evidence-only rule, identical for every variant and every step."""
        norm = mpn.strip().upper()
        return not norm or norm in self.evidence_mpns or norm in self.design_mpns

    def guard_mpns(self, items: list[BomItem], step: str) -> list[BomItem]:
        """Clear MPNs that are in no evidence and record the attempt (hallucination
        attempts stay measurable instead of disappearing)."""
        out: list[BomItem] = []
        for original in items:
            item = original
            if item.mpn and not self.mpn_allowed(item.mpn):
                self.issues.append(
                    Finding(
                        rule_id="agent.mpn_rejected",
                        severity=Severity.WARNING,
                        field="mpn",
                        refdes=list(item.refdes),
                        message=f"{step}: MPN {item.mpn!r} is in no "
                        "retrieved evidence and was discarded",
                    )
                )
                prov = {
                    k: v for k, v in item.provenance.items() if k not in {"mpn", "manufacturer"}
                }
                item = item.model_copy(update={"mpn": "", "manufacturer": "", "provenance": prov})
            out.append(item)
        return out

    async def guarded(self, node: str, fn: Callable[[], Awaitable[R]], default: R) -> R:
        """Run an agent step; a budget stop or model failure becomes a finding and the
        step's ``default`` (partial results are kept, the run is not aborted)."""
        try:
            return await self.step(node, fn)
        except BudgetExceededError as exc:
            self.budget_hit = True
            self.issues.append(
                Finding(rule_id="run.budget", severity=Severity.ERROR, message=f"{node}: {exc}")
            )
        except LlmError as exc:
            self.failed = True
            self.issues.append(
                Finding(rule_id="run.llm_error", severity=Severity.ERROR, message=f"{node}: {exc}")
            )
        return default

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
        max_tokens: int = 4096,
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
            max_tokens=max_tokens,
            prompt_id=prompt.id,
            prompt_version=prompt.full_version,
            model=model,
            messages=[Message("system", prompt.text), Message("user", "\n\n".join(parts))],
            schema_name=schema.__name__,
            json_schema=schema_of(schema),
            metadata={"run_id": self.run_id, "tenant_id": self.tenant_id, "prompt_id": prompt.id},
        )
        self.budget.check()
        try:
            result, usage = await structured(self.chat, request, schema)
        except LlmError as exc:
            self.budget.charge(exc.usage)  # failed attempts are paid for too
            counter = _step_calls.get()
            if counter is not None:
                counter[0] += exc.usage.llm_calls
            raise
        self.budget.charge(usage)
        counter = _step_calls.get()
        if counter is not None:
            counter[0] += usage.llm_calls
        return result, prompt, model

    async def step(self, node: str, fn: Callable[[], Awaitable[R]]) -> R:
        counter = [0]
        token = _step_calls.set(counter)
        start = time.perf_counter()
        try:
            with tracer.start_as_current_span(
                f"node {node}", attributes={"bomagent.node": node, "bomagent.run_id": self.run_id}
            ):
                return await fn()
        finally:
            _step_calls.reset(token)
            finished = TraceStep(
                node=node, duration_s=time.perf_counter() - start, llm_calls=counter[0]
            )
            self.trace.append(finished)
            if self.on_step is not None:
                try:
                    await self.on_step(finished, self.budget.usage.model_copy())
                except Exception:  # progress is best-effort; the result is what counts
                    log.warning("step progress callback failed (node %s)", node, exc_info=True)


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
