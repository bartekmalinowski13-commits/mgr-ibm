# M0 – Fundament (plan)

Źródła: `docs/ROADMAP.md` (M0), ADR-0001, ADR-0004, ADR-0010, ADR-0011, ADR-0012, `TESTING.md`.
Proces: brainstorming → plan → TDD → review subagentem → weryfikacja (superpowers niedostępne w sesji – proces prowadzony ręcznie, patrz `docs/STATUS.md`).

## Brainstorming – pytania i odpowiedzi (na podstawie dokumentów)
| Pytanie | Odpowiedź | Źródło / log |
|---|---|---|
| Gdzie żyją migracje, skoro baza jest wspólna dla 4 serwisów? | osobny pakiet `packages/py/db-migrations`, DDL pisane ręcznie | ADR-0016 |
| Jak testować RLS bez Dockera? | fixture: `BOMAGENT_TEST_DATABASE_URL` (natywny Postgres) albo Testcontainers; brak bazy = test **nie przechodzi** | `packages/py/testing` |
| Jak workery wystawiają `/healthz`? | ten sam FastAPI z pętlą konsumenta w `lifespan` | DECISIONS_LOG |
| Emulator S3/SQS | moto (Apache-2.0) | DECISIONS_LOG |
| Kiedy liczyć hash chain audytu? | trigger w bazie, pod blokadą doradczą per tenant | ADR-0011 |

## Zadania (TDD)
1. Workspace `uv` (13 pakietów) + `pnpm` + biome; ruff, mypy --strict, import-linter (kontrakty warstw i czystości domeny).
2. `platform-common`: `TenantContext`, `tenant_transaction` (`set_config('app.tenant_id', …, true)`), audyt, OTel, structlog z redakcją, problem+json, health, kolejki (SQS/in-memory, kontekst tenanta i śladu), magazyn obiektów z prefiksem tenanta.
3. `db-migrations` 0001: `app.current_tenant_id()`, `tenancy.tenants`, `audit.events` (append-only, hash chain, `verify_chain`).
4. Testy izolacji (`isolation`) + test katalogowy „każda tabela z `tenant_id` ma FORCE RLS”.
5. Szkielety 4 serwisów z `/healthz`, `/readyz`, śladami OTel.
6. `deploy/compose`: Postgres+pgvector, moto, LiteLLM + fake LLM, grafana/otel-lgtm, Langfuse (profil), Ollama (profil), serwisy; Dockerfile non-root.
7. CI: `pr.yml` (static, testy, izolacja, kontrakt, TS, stack+smoke+E2E, security, cdk), `codeql.yml`, `main.yml` (deploy za `vars.AWS_DEPLOY_ENABLED`), Dependabot, szablony PR/issue, pre-commit, gitleaks.

## Kryteria akceptacji
`just up && just smoke` (healthz + trace w Tempo) – **weryfikuje CI** (`stack-smoke`), bo w sesji nie ma Dockera; lokalnie: testy jednostkowe, integracyjne i izolacji zielone na natywnym Postgresie 16 + pgvector.
