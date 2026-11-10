"""Shared contract of all variant runtimes (ADR-0007):
``ParsedDesign + Requirements + RunConfig -> BomVersion + Trace + Usage``."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from bomagent_bom.model import BomVersion, ParsedDesign, Requirements, Usage

Variant = Literal["A", "B"]


class RunConfig(BaseModel):
    variant: Variant
    model_id: str = "fake-closed"
    fast_model_id: str | None = None  # tiering: cheap model for simple steps (defaults to model)
    max_repair_iterations: int = Field(default=2, ge=0, le=5)
    max_llm_calls: int = Field(default=200, ge=1)
    max_total_tokens: int = Field(default=2_000_000, ge=1)
    timeout_s: float = Field(default=900.0, gt=0)
    concurrency: int = Field(default=8, ge=1, le=64)
    kb_k: int = Field(default=5, ge=1, le=20)
    kb_snapshot_id: str | None = None
    seed: int = 0


class RunInput(BaseModel):
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    design: ParsedDesign
    requirements: Requirements = Field(default_factory=Requirements)
    config: RunConfig


class TraceStep(BaseModel):
    node: str
    duration_s: float
    llm_calls: int = 0
    detail: dict[str, object] = Field(default_factory=dict)


class RunOutput(BaseModel):
    run_id: uuid.UUID
    runtime: str
    bom: BomVersion
    trace: list[TraceStep]
    usage: Usage
    status: Literal["completed", "budget_exceeded", "failed"] = "completed"


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class Budget:
    """Per-run limits (R7): LLM calls, tokens, wall time."""

    config: RunConfig
    started: float = field(default_factory=time.monotonic)
    usage: Usage = field(default_factory=Usage)

    def charge(self, usage: Usage) -> None:
        self.usage = self.usage + usage

    def check(self) -> None:
        """Called *before* each model call: refuses the call that would exceed a limit."""
        c = self.config
        if self.usage.llm_calls >= c.max_llm_calls:
            raise BudgetExceededError(f"limit of {c.max_llm_calls} LLM calls reached")
        if self.usage.input_tokens + self.usage.output_tokens > c.max_total_tokens:
            raise BudgetExceededError(f"more than {c.max_total_tokens} tokens")
        if time.monotonic() - self.started > c.timeout_s:
            raise BudgetExceededError(f"run longer than {c.timeout_s} s")


class VariantRuntime(Protocol):
    name: str

    async def run(self, run: RunInput) -> RunOutput: ...
