# bomagent-agents (`bomagent_agents`)

**Responsibility:** agents, versioned prompts and the variant runtimes compared in the thesis
(ADR-0007): **A** - multi-agent, LLM only; **B** - hybrid (rules + LLM); **A-sdk** - variant A
on the Claude Agent SDK loop (experimental, Bedrock EU only).

## Public interface
- `get_runtime("A" | "B" | "A-sdk").run(design, requirements, RunConfig, Dependencies) -> RunResult`
  (`BomVersion` + `TraceStep[]` + `Usage` + config + model info; failed runs keep their trace).
- `Dependencies(chat=ChatClient, model=ModelSpec, retriever=Retriever)` - everything external is injected.
- `RunConfig` / `Budget` - experiment cell definition (variant, model, temperature, concurrency,
  top-k, KB snapshot) and limits (LLM calls, tokens, seconds, repair iterations, tool rounds).
- `KbRetriever` (tenant-scoped, short transaction per call, suspicious chunks dropped),
  `StaticRetriever` (folder of datasheets, offline).
- `prompts.PROMPTS` - every prompt has `id@version`; data is wrapped in `<data>`/`<excerpt>` and
  declared untrusted.
- `simulators.simulate` - deterministic stand-in for a model (tests, CI, offline CLI). Not research data.

## Testing
`uv run pytest packages/py/agents` (no database); `tests/isolation/test_agents_isolation.py` (Postgres).
