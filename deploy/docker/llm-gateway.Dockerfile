# syntax=docker/dockerfile:1.7
# LLM gateway (LiteLLM, ADR-0006). The config is rendered from the model catalogue in CI
# (python -m bomagent_llm.gateway_config > deploy/gateway/config.yaml) - it contains no
# secrets: Bedrock uses the task role, other providers read keys from the environment.
# Pin the base image by digest when the pipeline is enabled (supply chain, SECURITY.md).
ARG LITELLM_IMAGE=ghcr.io/berriai/litellm:v1.108.3
FROM ${LITELLM_IMAGE}
COPY --chmod=0444 deploy/gateway/config.yaml /app/config.yaml
# same non-root user as the ECS task definition (10001); the root FS is read-only there,
# writable paths: /tmp only. LITELLM_LOCAL_MODEL_COST_MAP avoids a download at start.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True HOME=/tmp
USER 10001:10001
EXPOSE 4000
CMD ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "2"]
