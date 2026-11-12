# ADR-0007: Agent runtime: LangGraph + Claude Agent SDK adapter

Status: Accepted · 2026-11-09

## Context
Two system variants to compare; a full step trace, resumption and speed are needed.

## Decision
A `VariantRuntime` interface. Implementations: `langgraph_a` (100% LLM), `langgraph_b` (hybrid), `claude_agent_sdk_a` (variant A on an off-the-shelf agentic loop). LangGraph checkpoints in Postgres. Parallel fan-out of items, model tiering, structured output, time/token budgets.

## Consequences
A fair comparison: the same input/output contract and the same domain libraries. Cost: maintaining two frameworks – the Claude Agent SDK in only one adapter.

## Alternatives considered
CrewAI/AutoGen (less control over state); a custom orchestrator (more code to maintain).
