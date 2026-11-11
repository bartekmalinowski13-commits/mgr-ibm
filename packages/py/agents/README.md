# bomagent-agents (`bomagent_agents`)

**Responsibility:** the two systems compared in the thesis, as interchangeable runtimes
behind one contract (ADR-0007): `RunInput(ParsedDesign, Requirements, RunConfig) ->
RunOutput(BomVersion, trace, usage, status)`.

| Runtime | Variant | What does the work |
|---|---|---|
| `langgraph_b` | B - hybrid | parser + deterministic grouping (`bom-core`) -> **MPN agent with RAG only for lines without MPN** (fan-out with LangGraph `Send`) -> rule pack `core` -> bounded **repair agent** on rule errors -> deterministic assembly |
| `langgraph_a` | A - LLM only | **extraction/grouping agent** -> MPN agent for **all** lines -> **validation agent** -> **composition agent**; code only converts JSON to `BomItem` |
| `claude_agent_sdk_a` | A on a ready-made loop | Claude Agent SDK with in-process MCP tools `get_components`, `search_kb`, `submit_bom`; no built-in tools (no shell/files/web). Optional dependency `claude-agent-sdk`; configure it for the LLM gateway or Bedrock EU |

Fair comparison: both variants use the same retriever, model, MPN prompt and evidence;
only the architecture differs (`docs/thesis/ARCHITEKTURA_WARIANTOW.md`).

## Safety and reproducibility
- Prompts are versioned files (`prompts/<id>.v<n>.md`); provenance records
  `<n>+<sha8>` of the exact text, the model id and the cited KB chunks.
- Document text and components are sent only inside `<data>` blocks and declared
  untrusted; KB chunks flagged as prompt injection are never sent.
- An MPN is accepted only if it appears among the retrieved evidence candidates;
  anything else is discarded (anti-hallucination by construction).
- Budgets per run: LLM calls, tokens, wall time (`RunConfig`); exceeding them stops the
  graph and returns the partial BOM with a `run.budget` finding.
- Checkpointer: `TenantCheckpointSaver` (`checkpoint.py`) keeps LangGraph checkpoints and
  pending writes in `runs.graph_checkpoints` / `runs.graph_writes` (migration 0012):
  tenant-scoped with RLS, thread = run id, deleted with the run. The agent worker uses it
  for runs started through the API (`context_factory(..., checkpointer=...)`); the CLI,
  experiments and unit tests keep the in-memory checkpointer. Each run executes once (the
  worker claims `queued -> running`); resuming a crashed run from its last checkpoint is
  not wired yet - the reaper fails stuck runs.
- Claude Agent SDK adapter: agent turns are capped by the run's LLM-call budget, the loop
  stops at the time budget, token overruns are reported as `budget_exceeded`, and the BOM
  records the run's KB snapshot like the LangGraph runtimes.

## Fake provider
`fake_responder.heuristic_responder` + `bomagent_llm.chat.FakeChat` answer
deterministically (cassettes first). `fake_server` exposes it OpenAI-compatibly for the
compose stack behind LiteLLM. It tests plumbing - thesis numbers come from real models.

## Testing
`uv run pytest packages/py/agents`; CLI: `uv run bomagent run evals/fixtures/kicad/ecg-frontend --variant A --reference evals/fixtures/kicad/ecg-frontend/reference_bom.csv`
