# bomagent-llm (`bomagent_llm`)

**Responsibility:** the only way the platform talks to models - through the LiteLLM
gateway (ADR-0006).

## Public interface (M2 part; chat/structured output in M3)
- `catalog.load_catalog()` - `models.yaml`: every model has `license_class`
  (`closed`/`open-weight`), `residency` (`eu-region`/`eu-geo`/`local`), tier, costs.
  `Catalog.get(id)` refuses unknown, disabled or **unverified** models: real model IDs
  ship `enabled: false, verified: false` until a human checks regional availability.
- `embeddings.GatewayEmbeddings` (OpenAI-compatible `/v1/embeddings` of the gateway,
  batched, OTel `gen_ai.*` spans) and `HashingEmbeddings` (deterministic, tests/offline).

## Testing
`uv run pytest packages/py/llm`
