# As built (2026-11)

Companion to `ARCHITECTURE.md` (the target, which stays the source of truth for the design). This file records
what the repository contains **today**, with a path as evidence for every row. It does not change any decision;
where the code differs from the target, that is a gap to close or a decision for a `docs(spec)` PR.
Resolves audit items ARCH-09 and DOC-01 (as-built part). Status per milestone: `docs/STATUS.md`.

Legend: **implemented** = code and tests in the repo; **configured** = infrastructure/config code exists and is
synthesised or composed, but nothing was deployed from a session (rule 6 of `CLAUDE.md`); **planned** = nothing in
the repo beyond the target description.

| Component (target) | Status | Evidence | Note |
|---|---|---|---|
| Tenant context + Postgres RLS | implemented | `packages/py/db-migrations/src/bomagent_migrations/rls.py`, `packages/py/platform-common/src/bomagent_common/tenancy.py`, `tests/isolation/` | cross-tenant isolation tests run in CI |
| Multi-tenant deployment model: pooled | implemented | `0001_foundation.py` (`deployment` column) | |
| Silo deployment (dedicated cluster + KMS key) | planned | `0001_foundation.py` only has the `'pooled'`/`'silo'` column | no connection routing by `tenant_id`, no per-tenant stack |
| API (REST, `/v1`, problem+json, OpenAPI) | implemented | `services/api/`, `services/api/openapi.json` | |
| Ingest, agent and KB-indexer workers | implemented | `services/ingest-worker/`, `services/agent-worker/`, `services/kb-indexer/` | |
| All-in-one image with process roles | implemented | `services/all-in-one/`, `deploy/docker/allinone.Dockerfile` | used by the Fly + Supabase pilot (`deploy/supabase/`) |
| CAD/EDA parsers in a sandboxed child | implemented | `packages/py/cad-parsers/`, `packages/py/cad-parsers/tests/test_sandbox.py` | process-level hardening; the separate no-egress ECS task is not provisioned |
| Malware scan before parsing: EICAR default, optional ClamAV | implemented | `services/ingest-worker/src/bomagent_ingest/scanner.py` | |
| Malware scan: GuardDuty Malware Protection for S3 | configured | `infra/cdk/lib/operations-stacks.ts` (`CfnMalwareProtectionPlan`) | not wired into the ingest decision; gating on the verdict is not implemented |
| Knowledge base: pgvector + full-text + rank fusion + reranker | implemented | `packages/py/kb/src/bomagent_kb/store.py` | reranker is lexical by default, pluggable |
| Variants A and B agents, rules, eval harness | implemented | `packages/py/agents/`, `packages/py/rules/`, `packages/py/eval/`, `packages/py/cli/` | |
| LLM gateway (LiteLLM) with EU policies | implemented / configured | `packages/py/llm/src/bomagent_llm/eu_guard.py`, `gateway_config.py`, `deploy/compose/litellm/config.yaml`, `deploy/gateway/README.md` | `check_environment` exists (`eu_guard.py`) but no service calls it at start |
| Per-tenant LLM budgets | partial | enforced in the API: `services/api/src/bomagent_api/plans.py`; the gateway only receives tenant/run tags (`packages/py/llm/src/bomagent_llm/chat.py`) and per-key budgets (`tools/pilot-llm-key.sh`) | no per-tenant budget in the gateway |
| OpenTelemetry traces and metrics (OTLP/HTTP) | implemented | `packages/py/platform-common/src/bomagent_common/telemetry.py`, `metrics.py` | |
| Local observability: Grafana LGTM image | configured | `deploy/compose/compose.yaml` (`otel-lgtm`) | |
| Langfuse LLM tracing | configured (local only) | `deploy/compose/compose.yaml` (profile `langfuse`), `justfile` (`just up`) | no Langfuse SDK or exporter in the application code; only metadata tags in `chat.py` |
| ADOT Collector, Managed Prometheus, Managed Grafana | planned | none in `infra/cdk/lib/` | CDK has CloudWatch alarms and an SNS topic only (`ObservabilityStack`) |
| EventBridge, event-driven audit archive | planned | none | the audit log is a hash-chained Postgres table with daily anchors (below) |
| Immutable audit log | implemented | `packages/py/platform-common/src/bomagent_common/audit.py`, `audit_anchor.py`, `services/api/src/bomagent_api/maintenance.py` | |
| Audit archive in write-once storage | configured | `infra/cdk/lib/data-stack.ts` (S3 Object Lock bucket) | anchors are written through an `AnchorSink` |
| Transactional e-mail (Amazon SES) | planned | none | invitations are links, no mail sender in code |
| Queues (SQS + DLQ) | implemented / configured | `packages/py/platform-common/src/bomagent_common/messaging.py`, `infra/cdk/lib/data-stack.ts` | |
| Identity: Cognito, SAML/OIDC per organisation | implemented / configured | `services/api/src/bomagent_api/sso.py`, `routers/sso.py`, `infra/cdk/lib/identity-stack.ts`, migration `0010_sso.py` | the live pilot uses Supabase Auth (`services/api/tests/test_supabase_auth.py`) |
| AWS infrastructure (VPC, Fargate, Aurora, edge, WAF, backup, CI/CD) | configured | `infra/cdk/lib/*.ts`, `infra/cdk/test/` (`just synth`) | never deployed from a session |
| Fly + Supabase pilot deployment | configured | `deploy/supabase/` (`fly.toml`, `gateway.fly.toml`), `.github/workflows/deploy-env.yml` | |
| Web app (React + Vite, PL/EN) | implemented | `apps/web/` | |

## Known deviations from the target text

- `ARCHITECTURE.md` shows Langfuse, ADOT/Prometheus/Grafana, EventBridge, SES and silo as parts of the system;
  per the table only Langfuse (local stack) and the Grafana LGTM image (local stack) exist.
- Per-tenant budgets live in the API plan limits, not in the gateway.
- Any change to the target itself belongs in a `docs(spec)` PR with a `docs/DECISIONS_LOG.md` row; this file only
  reports the state.
