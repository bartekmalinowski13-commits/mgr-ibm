# BOM Agent - task runner. `just --list` shows everything.
set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]

compose := "docker compose -f deploy/compose/compose.yaml"
py_modules := "-p bomagent_common -p bomagent_migrations -p bomagent_testing -p bomagent_bom -p bomagent_cad -p bomagent_rules -p bomagent_eval -p bomagent_llm -p bomagent_kb -p bomagent_agents -p bomagent_cli -p bomagent_api -p bomagent_ingest -p bomagent_agent_worker -p bomagent_kb_indexer"

default:
    @just --list

# install all dependencies (Python + TypeScript) and git hooks
bootstrap:
    uv sync --all-packages
    if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else pnpm install; fi
    uv run pre-commit install || true

# local stack: Postgres+pgvector, moto (S3/SQS), LiteLLM + fake LLM, OTel LGTM, Langfuse, services
up:
    COMPOSE_PROFILES=langfuse {{compose}} up -d --build --wait

# core stack only (no Langfuse) - what CI uses
up-core:
    {{compose}} up -d --build --wait api ingest-worker agent-worker kb-indexer litellm otel-lgtm

# optional local open-weight model
up-ollama:
    COMPOSE_PROFILES=ollama {{compose}} up -d ollama

down:
    COMPOSE_PROFILES=langfuse,ollama {{compose}} down

logs service="":
    {{compose}} logs -f {{service}}

# lint + format check + types + module boundaries
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy {{py_modules}}
    uv run lint-imports
    if [ -f pnpm-lock.yaml ]; then pnpm -r --if-present run lint && pnpm -r --if-present run typecheck; fi

fmt:
    uv run ruff format .
    uv run ruff check --fix .

# unit + integration + isolation tests with coverage (needs Postgres: see packages/py/testing)
test *args:
    uv run pytest -m "not smoke and not e2e" --cov --cov-report=term-missing:skip-covered {{args}}
    if [ -f pnpm-lock.yaml ]; then pnpm -r --if-present run test; fi

# fast loop: unit tests only (no database)
test-unit *args:
    uv run pytest -m "not integration and not smoke and not e2e" {{args}}

# cross-tenant isolation suite (blocking in CI)
test-isolation:
    uv run pytest -m isolation -v

# smoke tests against the running local stack
smoke:
    SMOKE_TEMPO_URL=${SMOKE_TEMPO_URL:-http://localhost:3200} uv run pytest -m smoke tests/smoke -v

# end-to-end UI tests (Playwright) against the local stack
e2e:
    pnpm --filter @bomagent/web exec playwright test --trace off

# AWS CDK synth + cdk-nag (never deploys)
synth:
    pnpm --filter @bomagent/infra run synth

# regenerate OpenAPI contract and TypeScript client
openapi:
    uv run python -m bomagent_api.openapi > services/api/openapi.json
    if [ -d packages/ts/api-client ]; then pnpm --filter @bomagent/api-client run generate; fi

# database migrations against BOMAGENT_MIGRATOR_DATABASE_URL
migrate:
    uv run bomagent-migrate upgrade
