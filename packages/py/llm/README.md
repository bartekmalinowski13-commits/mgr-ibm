# bomagent-llm (`bomagent_llm`)

**Responsibility:** the only way the platform talks to models - through the LiteLLM
gateway (ADR-0006).

## Public interface
- `catalog.load_catalog()` - `models.yaml`: every model has `license_class`
  (`closed`/`open-weight`), `residency` (`eu-region`/`eu-geo`/`local`), tier, costs.
  `Catalog.get(id)` refuses unknown, disabled or **unverified** models: real model IDs
  ship `enabled: false, verified: false` until a human checks regional availability.
- `embeddings.GatewayEmbeddings` (OpenAI-compatible `/v1/embeddings` of the gateway,
  batched, OTel `gen_ai.*` spans) and `HashingEmbeddings` (deterministic, tests/offline).

- `chat.GatewayChat` - chat completions through the gateway: structured output
  (`response_format` JSON Schema), tools (function calling), usage incl. cached tokens,
  `metadata` (prompt id/version, tenant, run) and `user=tenant_id` for per-tenant budgets.
- `fake.FakeChat` - deterministic provider: cassettes (`tests/cassettes`, key = hash of the
  request without tenant/run ids) -> simulator per prompt -> `FakeMissError`.
- `fake_server` - the same as an OpenAI-compatible server (`python -m bomagent_llm.fake_server`)
  behind LiteLLM in the local stack and CI.

## Testing
`uv run pytest packages/py/llm`
