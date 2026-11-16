# Rendered in CI by `python -m bomagent_llm.gateway_config`; do not edit.

## Start-up EU check (ARCH-08)

The image's entrypoint (`deploy/gateway/entrypoint.sh`) runs `python -m bomagent_llm.eu_guard`
before LiteLLM: a non-EU `AWS_REGION`/`AWS_DEFAULT_REGION`, a non-EU `AZURE_API_BASE`,
`MISTRAL_API_BASE` or Bedrock endpoint override stops the container with a message on stderr.
The config file itself is still rendered and checked at build time; moving to a signed runtime
config in object storage (the audit's later step) would reuse the same check.
