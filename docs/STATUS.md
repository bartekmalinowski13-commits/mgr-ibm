# Project status

> **Continue here:** `docs/HANDOFF.md` - remaining work in order, owner-side blockers, local demo, environment notes.

_Updated by Claude Code after every milestone (see `docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md` §5)._

## 2026-11-12 - deployment paths ready (AWS single-account dev, Supabase pilot); nothing deployed yet

> **Owner: start with `docs/OWNER_CHECKLIST.md`** - what is ready and your steps in order.

### Session 2026-11-12

- **Sample projects:** five CC0 designs (`evals/samples`), auto-added as `[Sample] ...` projects to every new organisation (`BOMAGENT_SEED_SAMPLES`), owner re-add (`POST /v1/samples`), delete of samples, web button + badge (PL/EN), owner guide `docs/owner-guides/PRZYKLADOWE_DANE.md`.

- **AWS, one account, dev only:** `bomagent:singleAccount` (ECR repositories + GitHub push role
  in the account), `bomagent:monthlyBudgetUsd` (AWS Budget with e-mail alerts),
  `DEPLOY_ENVIRONMENTS=dev` stops the pipeline after dev; runbook
  `docs/platform/runbooks/single-account-dev.md`.
- **Supabase pilot variant (ADR-0017, proposed):** PostgreSQL queue with RLS (migration 0013),
  queue backend switch, S3-compatible storage, Supabase JWT verification (asymmetric keys only,
  e-mail confirmed with Supabase Auth), database preparation as a non-superuser admin, one
  `services/all-in-one` container (API + workers + SPA), image + Fly.io config, web sign-in mode
  (e-mail + password); runbook `docs/platform/runbooks/supabase-pilot.md`; CI builds and runs the
  image.
- Security review of the Supabase variant: no CRITICAL/HIGH; M1, L1, L3 fixed, rest documented.
- Tests: 620 Python (+42 contract subtests), 36 infra, 26 web unit, 5 E2E - green.

## 2026-11-11 - M0-M5 and M7 done, M6 code done (not deployed), M8 tool done (real experiment waits for data)

> **Where the code is:** all work is on branch `claude/code-master-prompt-part-2-5651f9` (the
> session environment could push only there - see `docs/DECISIONS_LOG.md`). **Nothing is merged
> to `main`.** For review: a PR from this branch to `main` (squash); commits are split per
> milestone and per fix.

### What is done

| Milestone | Scope | State |
|---|---|---|
| M0 | monorepo (uv workspace + pnpm/biome), justfile, pre-commit, ruff / mypy --strict / import-linter, `platform-common` (tenant context, RLS, hash-chained audit, OTel, structlog with redaction, problem+json, SQS with tenant/trace context, S3 with tenant prefix), migration 0001 (roles without BYPASSRLS), 4 service skeletons with `/healthz` `/readyz`, `deploy/compose`, GitHub Actions (pinned SHAs), Dependabot | ✅ |
| M1 | `bom-core` (model with per-field provenance, normalisation, packages, grouping, CSV/JSON export), `cad-parsers` (KiCad 6-9 + CSV BOM), `rules` core@1.0.0 (incl. IEC 60601 flags), `eval` (P/R/F1, field accuracy, MPN coverage and hallucinations, error injection, repeatability), CLI `bomagent parse/bom/eval`, 3 KiCad fixtures (CC0) | ✅ |
| M2 | `llm` (EU model catalogue with a verification gate, embeddings), migration 0002 (`kb.*` with global/tenant RLS), `kb` (PDF extraction, chunking, hybrid pgvector + FTS + RRF + reranker, snapshots, corrections as tenant knowledge, prompt-injection flags), `kb-indexer` | ✅ |
| M3 | `llm.chat` (gateway with structured output, fake provider with cassettes), `agents`: versioned prompts, `VariantRuntime` contract, budgets, `langgraph_b` (hybrid), `langgraph_a` (100 % LLM), `claude_agent_sdk_a` adapter, MPNs only from KB evidence; `agent-worker` | ✅ |
| M4 | API `/v1` (OIDC JWT, local mock IdP only in local/test, memberships and roles from the DB, RBAC, projects, uploads, runs + SSE, BOM JSON/CSV, corrections -> new version + audit + KB, audit verification), OpenAPI 3.1 + Schemathesis, TS client, members and invitations, composite tenant FKs, API keys, plan limits, rate limiting and metering, transactional outbox + run reaper, **SSO per organisation** (verified domains, SAML/OIDC federated in Cognito, discovery, membership on first SSO sign-in, enforcement) | ✅ |
| M5 | `apps/web` (React/Vite/TanStack): sign-in (local + Cognito PKCE, e-mail first for SSO), onboarding, organisation switcher, templates, projects + upload, new run (A/B/both), live run steps (SSE), BOM with provenance panel and corrections, CSV export, A/B comparison, evaluation against a reference BOM, knowledge base, audit log, settings (members, invitations, API keys, usage, SSO); Playwright E2E + axe | ✅ |
| M6 | `infra/cdk`: 10 stacks, cdk-nag clean, assertion tests, `cdk synth` without credentials; SCPs; pipeline `main.yml` -> `deploy-env.yml` + `tools/deploy.sh` (disabled until `AWS_DEPLOY_ENABLED`); runbooks | ✅ code, **not deployed** (owner's step, `docs/platform/runbooks/`) |
| M7 | formats: IPC-2581, EDIF, ODB++, DXF parts lists, PDF BOM tables (cross-format consistency, XXE / entity expansion / path traversal / decompression bombs tested, hostile-input fuzz tests) | ✅ except PDF schematics/scans (OCR, vision) and native Altium/OrCAD/DWG (spikes + ADR first) |
| M8 | `bomagent experiment run <config.yaml>`: {A,B} x models x designs x repetitions, scoring against reference BOMs, paired permutation test + bootstrap CI, repeatability, manifest, validation effectiveness on injected errors, SVG figures + CSV tables for chapter 7; pilot on the fake LLM in `evals/reports/pilot-fake/` | 🟡 tool complete; needs >= 6 designs with verified reference BOMs and EU models enabled |

### Session 2026-11-11 (continuation)

- CI fix for the SSO commit (public discovery documents 400/429) - CI green again.
- **Local demo without Docker or LLM keys:** `just demo` (API + seeded tenant + web app on
  http://localhost:5173) - see `docs/HANDOFF.md`, "Local demo".
- **SSO security review:** 1 HIGH, 3 MEDIUM, 5 LOW, no cross-tenant issue. Fixed: HIGH-1
  (enforcement bypass by changing the account e-mail - now checked against the stored
  membership; e-mail not writable by users), MEDIUM-2 (Cognito app-client updates serialised
  across replicas), LOW-5 (Cognito touched only after preconditions; refused changes recorded
  and audited), OIDC secret never in error text. Rest in `DECISIONS_LOG.md`.
- **LangGraph checkpoints in PostgreSQL** with RLS (migration 0012, `TenantCheckpointSaver`),
  used by the agent worker for API runs.
- **Claude Agent SDK adapter:** run budget (turns, time, tokens) and KB snapshot recorded.
- **Deferred M4 low items closed** (migration 0011): storage quota per plan, upload races,
  idempotency hash bound to method + path, outbox retry limit (10 attempts and 24 h) + cleanup,
  composite FKs in `kb.*` and `api_keys.replaced_by`.
- **Parsing in a resource-limited subprocess** (`bomagent_cad.sandbox`: RLIMIT_AS 1 GiB, CPU
  60 s, wall 90 s, minimal env, non-dumpable worker), projects bounded to 50 files / 256 MiB;
  workers take one message at a time.
- **`sslmode=verify-full`** to RDS with the pinned RDS CA bundle (all AWS connection paths).
- **Documentation translated to English** (thesis and supervisor report stay Polish).
- Reviews by subagents for every change above; all CRITICAL/HIGH findings fixed, the rest in
  `DECISIONS_LOG.md`.

### How to run

```bash
just bootstrap                       # uv sync --all-packages + pnpm install + pre-commit
just demo                            # local demo: http://localhost:5173 (docs/HANDOFF.md)
# tests with a database: PostgreSQL 16 + pgvector; either Docker (Testcontainers) or:
export BOMAGENT_TEST_DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/postgres
just test                            # unit + integration + isolation, with coverage
just test-isolation                  # tenant isolation only (blocking in CI)
just lint                            # ruff, mypy --strict, import-linter, biome
just openapi                         # regenerate openapi.json + TS client types
just e2e                             # Playwright + axe (with the API running on :8000)
uv run bomagent run evals/fixtures/kicad/ecg-frontend --variant B --reference evals/fixtures/kicad/ecg-frontend/reference_bom.csv
uv run bomagent experiment run evals/experiments/pilot-fake.yaml   # report: evals/reports/pilot-fake/report.md
```

### Test results (2026-11-11, local, Python 3.13, PostgreSQL 16 + pgvector)

- Full Python suite: **541 passed** (+ 42 Schemathesis contract subtests), including the
  tenant isolation suite; `tools/devstack.py --seed` (local demo) verified end to end.
- Coverage thresholds (packages 85 %, services 75 %) met in CI.
- ruff, ruff format, mypy --strict, import-linter (2 contracts), biome, TS typecheck - clean.

### Known limitations

- Docker is not available in the cloud session: the compose stack runs only in CI.
- The Claude Agent SDK adapter is tested with a scripted stand-in for the SDK's `query` loop.
- Langfuse tracing is unverified locally (only in the Docker stack).
- Automatic resume of a crashed run from its last checkpoint is not wired (the reaper fails
  stuck runs).
- `kicad-cli` cross-check not available; parsers are tested on own fixtures.
- Rule pack `core@1.0.0` changed in review fixes but was not used in any experiment yet -
  version not bumped.

### What I need from the owner

See `docs/HANDOFF.md`, "Blocked on the owner" (merge, experiment data, EU model access, AWS +
domain) and the assumptions awaiting acceptance (`docs/DECISIONS_LOG.md`, last column "yes").

## 2026-11-09 - starting point

- Done: thesis template (DOCX), thesis structure, A/B variant diagram, UI flow prototype (HTML),
  production architecture, 15 ADRs, UX guidelines, roadmap M0-M8, Claude Code prompt.
- No application code yet - start from M0.
