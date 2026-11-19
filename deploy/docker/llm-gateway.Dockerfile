# syntax=docker/dockerfile:1.7
# LLM gateway (LiteLLM, ADR-0006). The config is rendered at BUILD time from the model
# catalogue (bomagent_llm.gateway_config): only enabled + verified entries, EU-checked by
# bomagent_llm.eu_guard (the build fails on a non-EU region, profile or endpoint). The file
# contains no secrets: providers read keys from environment variables at run time
# (MISTRAL_API_KEY, AZURE_API_KEY, AZURE_API_BASE, AWS_*, LITELLM_MASTER_KEY).
#   docker build -f deploy/docker/llm-gateway.Dockerfile -t bomagent-llm-gateway .   # repo root
# Pin the base images by digest when a pipeline builds this image (supply chain, SECURITY.md).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG LITELLM_IMAGE=ghcr.io/berriai/litellm:v1.108.3

# ---------------------------------------------------------------- render the config
FROM ${PYTHON_IMAGE} AS render
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages/py ./packages/py
COPY services ./services
# default region of Bedrock entries without their own ``region`` (never a non-EU one)
ARG GATEWAY_REGION=eu-central-1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package bomagent-llm --no-editable \
    && /src/.venv/bin/python -m bomagent_llm.gateway_config --region "${GATEWAY_REGION}" > /config.yaml

# ---------------------------------------------------------------- gateway
FROM ${LITELLM_IMAGE}
COPY --from=render --chmod=0444 /config.yaml /app/config.yaml
# non-root (10001, as in the ECS task definition); writable path: /tmp only.
# LITELLM_LOCAL_MODEL_COST_MAP avoids a download at start.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True HOME=/tmp
USER 10001:10001
EXPOSE 4000
# Dual-stack: an EMPTY host makes uvicorn's asyncio server bind every address family of the
# host (one socket on 0.0.0.0 and one on ::). "::" alone is IPv6-only (asyncio sets
# IPV6_V6ONLY), which broke the IPv4-only AWS VPC (Service Connect http://litellm:4000);
# "0.0.0.0" alone breaks Fly's IPv6 6PN network. CI starts the image and probes both.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python3", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=4)"]
CMD ["--config", "/app/config.yaml", "--host", "", "--port", "4000", "--num_workers", "1"]
