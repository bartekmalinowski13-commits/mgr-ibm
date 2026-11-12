# M0 – Foundation (plan)

Sources: `docs/ROADMAP.md` (M0), ADR-0001, ADR-0004, ADR-0010, ADR-0011, ADR-0012, `TESTING.md`.
Process: brainstorming → plan → TDD → subagent review → verification (superpowers unavailable in the session – process carried out manually, see `docs/STATUS.md`).

## Brainstorming – questions and answers (based on the documents)
| Question | Answer | Source / log |
|---|---|---|
| Where do migrations live, given that the database is shared by 4 services? | a separate `packages/py/db-migrations` package, hand-written DDL | ADR-0016 |
| How to test RLS without Docker? | fixture: `BOMAGENT_TEST_DATABASE_URL` (native Postgres) or Testcontainers; no database = the test **fails** | `packages/py/testing` |
| How do workers expose `/healthz`? | the same FastAPI with the consumer loop in `lifespan` | DECISIONS_LOG |
| S3/SQS emulator | moto (Apache-2.0) | DECISIONS_LOG |
| When to compute the audit hash chain? | a database trigger, under a per-tenant advisory lock | ADR-0011 |

## Tasks (TDD)
1. `uv` workspace (13 packages) + `pnpm` + biome; ruff, mypy --strict, import-linter (layer contracts and domain purity).
2. `platform-common`: `TenantContext`, `tenant_transaction` (`set_config('app.tenant_id', …, true)`), audit, OTel, structlog with redaction, problem+json, health, queues (SQS/in-memory, tenant and trace context), object store with a tenant prefix.
3. `db-migrations` 0001: `app.current_tenant_id()`, `tenancy.tenants`, `audit.events` (append-only, hash chain, `verify_chain`).
4. Isolation tests (`isolation`) + a catalog test "every table with `tenant_id` has FORCE RLS".
5. Skeletons of the 4 services with `/healthz`, `/readyz`, OTel traces.
6. `deploy/compose`: Postgres+pgvector, moto, LiteLLM + fake LLM, grafana/otel-lgtm, Langfuse (profile), Ollama (profile), services; non-root Dockerfile.
7. CI: `pr.yml` (static, tests, isolation, contract, TS, stack+smoke+E2E, security, cdk), `codeql.yml`, `main.yml` (deploy behind `vars.AWS_DEPLOY_ENABLED`), Dependabot, PR/issue templates, pre-commit, gitleaks.

## Acceptance criteria
`just up && just smoke` (healthz + trace in Tempo) – **verified by CI** (`stack-smoke`), because there is no Docker in the session; locally: unit, integration and isolation tests green on native Postgres 16 + pgvector.
