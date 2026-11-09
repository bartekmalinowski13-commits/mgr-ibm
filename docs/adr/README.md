# Architecture Decision Records

Format: Kontekst → Decyzja → Konsekwencje → Rozważane alternatywy. Status wszystkich: **Zaakceptowany** (2026-11-09). Nowa decyzja = nowy plik z kolejnym numerem; zmiana decyzji = nowy ADR, który zastępuje stary.

| Nr | Decyzja |
|---|---|
| [0001](0001-monorepo-modular-services.md) | Monorepo i modułowe serwisy zamiast monolitu lub drobnych mikroserwisów |
| [0002](0002-aws-eu-only.md) | AWS, wyłącznie regiony UE, wiele kont |
| [0003](0003-compute-ecs-fargate.md) | ECS Fargate + SQS; Lambda tylko do kleju; bez Kubernetes |
| [0004](0004-multi-tenancy-pooled-rls.md) | Multi-tenancy: model pooled z Postgres RLS, silo dla planu Enterprise |
| [0005](0005-identity-oidc-cognito.md) | Tożsamość: OIDC, Amazon Cognito, SSO per organizacja |
| [0006](0006-llm-gateway-eu-providers.md) | LLM Gateway (LiteLLM) i dostawcy z przetwarzaniem w UE |
| [0007](0007-agent-runtime-langgraph.md) | Runtime agentów: LangGraph + adapter Claude Agent SDK |
| [0008](0008-knowledge-base-pgvector-scopes.md) | Baza wiedzy: pgvector, zakres globalny + przestrzenie per tenant |
| [0009](0009-ingestion-parser-plugins.md) | Ingestia: wtyczki parserów w izolowanym workerze |
| [0010](0010-observability-otel.md) | Obserwowalność: OpenTelemetry + Langfuse |
| [0011](0011-audit-append-only.md) | Audyt: log append-only z łańcuchem skrótów i Object Lock |
| [0012](0012-cicd-testing.md) | CI/CD w GitHub Actions i strategia testów |
| [0013](0013-iac-cdk-typescript.md) | IaC: AWS CDK w TypeScript + cdk-nag |
| [0014](0014-frontend-react-shadcn.md) | Frontend: React + Vite + shadcn/ui |
| [0015](0015-api-rest-openapi.md) | API: REST + OpenAPI 3.1 + SSE |
| [0016](0016-db-migrations-package.md) | Jeden pakiet migracji z ręcznie pisanym DDL i rolami bazy |
