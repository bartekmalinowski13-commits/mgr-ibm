# M3 – Agents, variants A and B (plan)

Sources: ROADMAP M3, ADR-0006, ADR-0007, ARCHITEKTURA_WARIANTOW.md, SECURITY.md.

## Brainstorming – questions and answers
| Question | Decision | Rationale |
|---|---|---|
| How to ensure A and B are comparable? | the same retriever, model, MPN-selection prompt and the "MPN only from evidence" rule | differences attributable to the architecture |
| What does the LLM do in B? | only MPN selection for items without an MPN + repair after rule errors | ARCHITEKTURA_WARIANTOW (step table) |
| What does code do in A? | only the JSON → `BomItem` conversion (no grouping/quantities) | "100% LLM" |
| Fan-out and concurrency | LangGraph `Send` + `max_concurrency` from `RunConfig` | R7 (speed) |
| Structured output | JSON Schema in `response_format`, Pydantic validation, 1 retry | R7, no parsing loop |
| Checkpoints | memory; Postgres once the tables with RLS are designed | tenant isolation > convenience |
| Claude Agent SDK | adapter with in-process MCP tools, no built-in tools | ADR-0007, SECURITY.md |

## Tasks – status
1. `llm.chat` (gateway + fake + cassettes) – ✅
2. versioned prompts, the `VariantRuntime` contract, budgets, retrievers – ✅
3. `langgraph_b`, `langgraph_a`, `claude_agent_sdk_a` – ✅
4. `fake_server` (compose), CLI `bomagent run`, `agent-worker` – ✅

## Acceptance criteria
A run of A and B on the KiCad fixture with a fake LLM produces a BOM (tests in `packages/py/agents`, `services/agent-worker`); step trace: `RunOutput.trace` + OTel spans `node *` and `chat *` (`gen_ai.*` attributes); the CLI `bomagent run --variant A|B` works. The trace in Langfuse – via the OTel callback in LiteLLM (compose), not verified locally (no Docker).
