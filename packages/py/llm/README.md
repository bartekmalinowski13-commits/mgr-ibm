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

- `chat.GatewayChat` - `/v1/chat/completions` with `response_format=json_schema`,
  GenAI OTel spans, `Usage` with cost from the catalogue; `structured()` validates against a
  Pydantic schema (one retry); `FakeChat` replays cassettes (`record_cassette`) or a
  scripted responder - CI never calls a real model.

- `eu_guard` - EU-only enforcement: `check_catalog` (enabled entries) and
  `check_gateway_config` (rendered LiteLLM config: Bedrock `eu.` profiles and EU regions,
  EU Azure regions, only api.mistral.ai / Azure / EU Bedrock endpoints, no DashScope).
  `gateway_config.render` raises `EuResidencyError` on any violation.

## Testing
`uv run pytest packages/py/llm`
