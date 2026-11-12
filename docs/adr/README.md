# Architecture Decision Records

Format: Context → Decision → Consequences → Alternatives considered. Status of all: **Accepted** (2026-11-09). A new decision = a new file with the next number; changing a decision = a new ADR that supersedes the old one.

| No. | Decision |
|---|---|
| [0001](0001-monorepo-modular-services.md) | Monorepo and modular services instead of a monolith or fine-grained microservices |
| [0002](0002-aws-eu-only.md) | AWS, EU regions only, multiple accounts |
| [0003](0003-compute-ecs-fargate.md) | ECS Fargate + SQS; Lambda only for glue; no Kubernetes |
| [0004](0004-multi-tenancy-pooled-rls.md) | Multi-tenancy: pooled model with Postgres RLS, silo for the Enterprise plan |
| [0005](0005-identity-oidc-cognito.md) | Identity: OIDC, Amazon Cognito, SSO per organization |
| [0006](0006-llm-gateway-eu-providers.md) | LLM Gateway (LiteLLM) and providers with processing in the EU |
| [0007](0007-agent-runtime-langgraph.md) | Agent runtime: LangGraph + Claude Agent SDK adapter |
| [0008](0008-knowledge-base-pgvector-scopes.md) | Knowledge base: pgvector, global scope + per-tenant spaces |
| [0009](0009-ingestion-parser-plugins.md) | Ingestion: parser plugins in an isolated worker |
| [0010](0010-observability-otel.md) | Observability: OpenTelemetry + Langfuse |
| [0011](0011-audit-append-only.md) | Audit: append-only log with a hash chain and Object Lock |
| [0012](0012-cicd-testing.md) | CI/CD in GitHub Actions and the testing strategy |
| [0013](0013-iac-cdk-typescript.md) | IaC: AWS CDK in TypeScript + cdk-nag |
| [0014](0014-frontend-react-shadcn.md) | Frontend: React + Vite + shadcn/ui |
| [0015](0015-api-rest-openapi.md) | API: REST + OpenAPI 3.1 + SSE |
| [0016](0016-db-migrations-package.md) | One migration package with hand-written DDL and database roles |
| [0017](0017-supabase-pilot-variant.md) | Second, lightweight deployment variant on Supabase (EU) for pilots (proposed) |
