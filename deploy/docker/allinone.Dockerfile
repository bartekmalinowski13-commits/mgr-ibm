# syntax=docker/dockerfile:1.7
# Supabase pilot: ONE image with the API, the ingest/agent/KB workers and the built SPA
# (services/all-in-one, deploy/supabase/README.md). Host-agnostic: everything is
# configured through environment variables; nothing host-specific is baked in.
#   docker build -f deploy/docker/allinone.Dockerfile -t bomagent-allinone .
# Commands: default `python -m bomagent_allinone` (serve on :8000);
#           `python -m bomagent_allinone migrate` / `bootstrap` (database, see README).
# Supabase presents certificates of public / Supabase CAs: no RDS bundle here (unlike
# python-service.Dockerfile); set BOMAGENT_DB_SSL_ROOT_CERT only with a mounted CA file.
# Pin the base images by digest when a pipeline builds this image (supply chain, SECURITY.md).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim

# ---------------------------------------------------------------- web app (static files)
FROM ${NODE_IMAGE} AS web
ENV CI=true PNPM_HOME=/pnpm
# the pnpm version of package.json "packageManager"
RUN npm install --global pnpm@10.28.0
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml biome.json ./
# infra/cdk is a workspace member: its manifest keeps the lockfile consistent, its
# dependencies are not installed (only the web app's closure is)
COPY infra/cdk/package.json ./infra/cdk/package.json
COPY packages/ts ./packages/ts
COPY apps/web ./apps/web
RUN --mount=type=cache,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm install --frozen-lockfile --filter "@bomagent/web..." \
    && pnpm --filter @bomagent/web run build

# ---------------------------------------------------------------- Python virtualenv
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages/py ./packages/py
COPY services ./services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package bomagent-all-in-one --no-editable

# ---------------------------------------------------------------- runtime (non-root)
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/src/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 \
    BOMAGENT_STATIC_DIR=/app/web BOMAGENT_PORT=8000
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build --chown=root:root /src/.venv /src/.venv
COPY --from=web --chown=root:root /src/apps/web/dist /app/web
USER 10001:10001
WORKDIR /tmp
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["python", "-m", "bomagent_allinone", "serve"]
