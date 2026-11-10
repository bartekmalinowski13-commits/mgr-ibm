"""Run configuration, budgets, trace and the LLM wrapper shared by all agents."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bomagent_agents.prompts import Prompt
from bomagent_bom.model import KbCitation, Provenance, ProvenanceKind, Usage
from bomagent_llm.catalog import ModelSpec
from bomagent_llm.chat import ChatClient, ChatMessage, ChatRequest, ChatResponse, ToolSpec

tracer = trace.get_tracer(__name__)
T = TypeVar("T", bound=BaseModel)


class BudgetExceededError(RuntimeError):
    """A run hit its limit of LLM calls, tokens, time or iterations."""


class AgentOutputError(RuntimeError):
    """The model did not produce valid structured output after a retry."""


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_llm_calls: int = Field(default=400, ge=1)
    max_total_tokens: int = Field(default=2_000_000, ge=1)
    max_seconds: float = Field(default=900.0, gt=0)
    max_repair_iterations: int = Field(default=2, ge=0)
    max_tool_rounds: int = Field(default=40, ge=1)


class RunConfig(BaseModel):
    """Everything that defines an experiment cell (recorded with the result)."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: str = "local"
    variant: str = "B"
    model_id: str = "fake-closed"
    temperature: float = 0.0
    concurrency: int = Field(default=4, ge=1, le=32)
    kb_top_k: int = Field(default=6, ge=1, le=20)
    kb_snapshot_id: str | None = None
    budget: Budget = Field(default_factory=Budget)


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    kind: Literal["llm", "rule", "tool", "parser"]
    agent: str = ""
    status: Literal["ok", "error", "skipped"] = "ok"
    summary: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_s: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class RunState:
    """Mutable per-run accounting (usage, trace, budget checks). Not stored in graph state."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.usage = Usage()
        self.trace: list[TraceStep] = []
        self._t0 = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def check_budget(self) -> None:
        b = self.config.budget
        if self.usage.llm_calls >= b.max_llm_calls:
            raise BudgetExceededError(f"LLM call budget of {b.max_llm_calls} exhausted")
        if self.usage.input_tokens + self.usage.output_tokens >= b.max_total_tokens:
            raise BudgetExceededError(f"token budget of {b.max_total_tokens} exhausted")
        if self.elapsed >= b.max_seconds:
            raise BudgetExceededError(f"time budget of {b.max_seconds:.0f} s exhausted")

    async def add_usage(self, usage: Usage) -> None:
        async with self._lock:
            self.usage = self.usage + usage

    def step(
        self, step: str, kind: Literal["llm", "rule", "tool", "parser"], agent: str = ""
    ) -> StepTimer:
        return StepTimer(self, step, kind, agent)


class StepTimer:
    """``with state.step("select", "llm", "selector") as s: ...`` records a trace step."""

    def __init__(
        self, state: RunState, step: str, kind: Literal["llm", "rule", "tool", "parser"], agent: str
    ) -> None:
        self.state = state
        self.record = TraceStep(step=step, kind=kind, agent=agent)
        self._t0 = 0.0
        self._usage0 = Usage()
        self._span: Any = None

    def __enter__(self) -> StepTimer:
        self._t0 = time.monotonic()
        self._usage0 = self.state.usage
        self._span = tracer.start_as_current_span(
            f"agents.{self.record.step}",
            attributes={
                "bomagent.step.kind": self.record.kind,
                "bomagent.agent": self.record.agent,
            },
        )
        self._span.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        u = self.state.usage
        self.record.duration_s = round(time.monotonic() - self._t0, 4)
        self.record.llm_calls = u.llm_calls - self._usage0.llm_calls
        self.record.input_tokens = u.input_tokens - self._usage0.input_tokens
        self.record.output_tokens = u.output_tokens - self._usage0.output_tokens
        if exc is not None:
            self.record.status = "error"
            self.record.summary = self.record.summary or f"{type(exc).__name__}: {exc}"[:500]
        self.state.trace.append(self.record)
        self._span.__exit__(exc_type, exc, tb)

    def note(self, summary: str) -> None:
        self.record.summary = summary[:500]


class AgentLLM:
    """LLM access for one run: model spec, accounting, budget checks, structured output."""

    def __init__(self, client: ChatClient, spec: ModelSpec, state: RunState) -> None:
        self.client = client
        self.spec = spec
        self.state = state

    def provenance(
        self,
        agent: str,
        prompt: Prompt,
        citations: list[KbCitation] | None = None,
        rationale: str = "",
    ) -> Provenance:
        return Provenance(
            kind=ProvenanceKind.AGENT,
            agent=agent,
            model_id=self.spec.id,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            citations=citations or [],
            rationale=rationale[:2000],
        )

    def _request(
        self,
        prompt: Prompt,
        agent: str,
        messages: list[ChatMessage],
        schema: type[BaseModel] | None,
        tools: list[ToolSpec] | None = None,
    ) -> ChatRequest:
        cfg = self.state.config
        return ChatRequest(
            model=self.spec.gateway_model,
            messages=messages,
            response_schema=schema.model_json_schema() if schema is not None else None,
            schema_name=schema.__name__ if schema is not None else None,
            tools=tools or [],
            temperature=cfg.temperature,
            metadata={
                "prompt_id": prompt.id,
                "prompt_version": prompt.version,
                "agent": agent,
                "tenant_id": cfg.tenant_id,
                "run_id": str(cfg.run_id),
                "variant": cfg.variant,
            },
        )

    async def call(self, request: ChatRequest) -> ChatResponse:
        self.state.check_budget()
        resp = await self.client.complete(request)
        await self.state.add_usage(
            Usage(
                llm_calls=1,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cached_input_tokens=resp.cached_input_tokens,
                cost_eur=self.spec.cost(resp.input_tokens, resp.output_tokens),
            )
        )
        return resp

    async def structured(
        self,
        prompt: Prompt,
        agent: str,
        schema: type[T],
        *,
        messages: list[ChatMessage] | None = None,
        **values: Any,
    ) -> T:
        """Render ``prompt`` (or use ``messages``), call the model, parse ``schema``; one retry
        with the validation error appended."""
        if messages is None:
            system, user = prompt.render(**values)
            messages = [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ]
        for attempt in range(2):
            resp = await self.call(self._request(prompt, agent, messages, schema))
            try:
                return schema.model_validate(json.loads(resp.content or "null"))
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt == 1:
                    raise AgentOutputError(
                        f"{agent}: invalid {schema.__name__} after retry: {str(exc)[:300]}"
                    ) from exc
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=resp.content),
                    ChatMessage(
                        role="user",
                        content=f"The answer is not valid {schema.__name__} JSON: "
                        f"{str(exc)[:500]}. Answer again with valid JSON only.",
                    ),
                ]
        raise AssertionError("unreachable")  # pragma: no cover
