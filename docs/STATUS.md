# Project status

> **Continue here:** `docs/HANDOFF.md` - remaining work in order, owner-side blockers, local demo, environment notes.

_Updated by Claude Code after every milestone (see `docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md` §5)._

## 2026-11-17 - audit PRs merged, Mistral enabled in the catalogue

- Merged on request of the owner: migrations 0015 (SECURITY DEFINER `tenancy.create_organization`, the platform role loses direct INSERT on tenants and memberships) and 0016 (concurrent indexes), the Supabase access-token hook SQL and runbook, step-up MFA (`BOMAGENT_MFA_ENFORCED`, off by default), SSO hardening (discovery as POST: the web app and API ship in one image and must be deployed together), the rest of the ARCH-04 service/repository layers, and the downgrade round-trip test with the fixes it needed (revisions 0010 and 0003).
- `mistral-large-eu` is `enabled` and `verified` (EU endpoint `api.eu.mistral.ai`). The pilot still runs on the fake model until the gateway is deployed and `BOMAGENT_ALLOW_FAKE_LLM` is removed (`docs/platform/runbooks/llm-gateway-pilot.md`).
- Open on purpose: #37 (gateway EU check at start) and #28 (Fly process groups), both `deploy/*`; see `docs/audit/PROGRESS.md`.
- Nothing is deployed: the next `fly deploy` runs the new migrations as its release command.

## 2026-11-16 - audit implementation (docs/audit/PROGRESS.md)

- **UX-01 demo mode visible:** `/config.json` carries `mode` (`demo`|`live`), `llm`, `embeddings`;
  `/readyz` also reports `embeddings`; the SPA shows a persistent PL/EN banner on demo deployments
  (fake model) and a note on the reference comparison; CSV export gets a `Demo` column and
  `GET /v1/runs/{id}/bom` returns `demo: true`.

- **SEC-03 (part 1) per-IP limits:** token buckets per client address for the routes that run before
  the organisation context (`/v1/sso/discover`, `/v1/invitations/accept`, `POST /v1/organizations`,
  `/v1/me`, every `/v1` request without credentials); 429 problem+json with `Retry-After`; address from
  `Fly-Client-IP` / a configured edge header, never `X-Forwarded-For`; outside local/test on only when
  `BOMAGENT_CLIENT_IP_HEADER` is set (`BOMAGENT_IP_RATE_LIMIT` overrides); the all-in-one image picks
  `Fly-Client-IP` automatically on Fly; failed token verifications (401) are counted per IP; the SPA
  shows a retry message on 429 at sign-in. In-memory, per replica. AWS needs the CloudFront header
  forwarded (owner/CDK PR).

- **SEC-13 (part) streamed uploads:** the API no longer reads a 64 MiB file into memory: the multipart
  body (already spooled to disk) is hashed in 1 MiB chunks, refused as soon as it crosses the limit,
  and streamed to the object store (`ObjectStore.put_file`; S3 multipart bounded to 2 parts of 8 MiB
  in flight, about 16 MiB per upload instead of the whole file).

- **SEC-01 (code part) parse child hardening:** `no_new_privs`, `RLIMIT_NOFILE` 32, `RLIMIT_FSIZE` 0,
  empty network namespace where `unshare(CLONE_NEWNET)` is allowed (no user-namespace fallback; outcome logged once; warning when the host
  does not allow it). The no-egress parser process group is still the real boundary (ARCH-02).

- **OPS-02 (code) metrics:** `bomagent_common.metrics` (runs, run duration, LLM calls/tokens/cost per
  model and tenant, parse outcomes and durations, outbox sent/dead, queue dead letters), OTLP metrics
  export next to the traces (`BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT`), an in-memory reader always
  attached. Dashboards and alert rules: see `deploy/observability/` (owner PR).

- **SEC-04 (part 1) source IP in the audit log:** the API middleware (`install_origin`) puts the caller's
  address (trusted edge header, else socket peer; one valid IP only) in a request-scoped context and
  `emit_audit` stores it in `audit.events.source_ip`. Worker-written events have no address.
  Still open: user agent (needs a column), anchor export, partitioning.

- **SEC-04 (part 2) audit chain anchors:** once a day per tenant the maintenance sweep writes
  `audit-anchors/<tenant>/<date>.json` (`seq`, `hash`) to a write-once sink (`BOMAGENT_AUDIT_ANCHOR_DIR`
  or `BOMAGENT_AUDIT_ANCHOR_BUCKET`, S3-compatible via `..._ENDPOINT_URL`); `GET /v1/audit-events/verify`
  compares the chain with the stored anchors. Nothing is exported until the owner configures a sink.

- **DOC-02 / ARCH-01 governance:** `tools/decisions_pending.py` lists `DECISIONS_LOG` rows that wait for
  the owner (64 of 93 today), a weekly workflow (`decisions-pending.yml`) flags rows older than 60 days
  (visibility only); draft **ADR-0018** (deployment tiers: Standard = Fly + Supabase, Enterprise = AWS)
  for the owner to accept together with ADR-0017.

- **SEC-08 pilot keys:** `tools/pilot-llm-key.sh` creates or rotates the app's LiteLLM virtual key (budget,
  expiry, only the models the gateway serves) and hands it to Fly through stdin - the master key is read
  silently and given to curl on stdin, nothing is printed or written; `pilot-llm-setup.sh` no longer writes
  a vault file (the master key is shown once); runbook `docs/platform/runbooks/key-rotation.md` has the
  key inventory and rotation steps. Tests drive the script with stub `fly`/`curl`.

- **ARCH-02 (code) process roles:** `BOMAGENT_ROLE` = `all` (default, unchanged) / `web` (API + SPA, no
  consumers) / `worker` (the three queue consumers and the dead-letter purge; no SPA or sign-in config, no
  outbox relay or reaper). Lets Fly run web and workers as separate process groups; the Fly config
  change is a `deploy/*` PR for the owner.

- **TH-01 attempted hallucinations (thesis):** `evaluate` reports `attempted_mpn_hallucination_rate` =
  rejected MPN decisions (`agent.mpn_rejected` findings) / all agent MPN decisions (agent-provenance MPNs
  kept + rejected); the final-BOM `mpn_hallucination_rate` stays as the residual. Both are in the experiment
  tables/figures; `docs/thesis/METODYKA.md` states which deterministic parts A and B share.

- **Fly process groups + observability assets (PR for the owner, `deploy/*`):** `fly.toml` runs `web`
  (public, always on, maintenance) and `worker` (no public port, own `/readyz` check, smaller DB pool) as
  groups of one app; `deploy/observability/` has a Grafana dashboard, Prometheus-style alert rules and the
  owner steps (EU OTLP endpoint, uptime probe); a test keeps dashboards/alerts consistent with the metrics
  the code defines. Metric names no longer carry OTel units, so exported names equal the code names.

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

## 2026-11-16 - TH-01 merged (#29)

- `attempted_mpn_hallucination_rate` (+ decision counts) in the eval summary, experiment key
  metrics and quality figure; lying-model end-to-end tests for A and B; methodology note in
  `docs/thesis/METODYKA.md`. A-unguarded ablation still to do.

## 2026-11-16 - TH-05 (code part)

- Catalogue entries carry `price_source_url` and `price_checked_on`; a test requires both on any
  hosted entry that is enabled or verified. Experiment `manifest.json` now records
  `model_ids` (gateway model per catalogue id) and `sampling` (temperature, seed, note that hosted
  models are not deterministic even at temperature 0).
- Owner: real prices from provider price lists, model access and flipping `enabled`/`verified`.

## 2026-11-16 - TH-02 (manifest part)

- Experiment `manifest.json` has a `retrieval` block: retriever type, embedding, reranker,
  `kb_dir`, `kb_snapshot_id` (sha256 of the datasheet files) and file count. Limitation of the
  hashing retriever written up in `docs/thesis/METODYKA.md`.
- Still to do: `experiment run --retriever postgres --embedding-model <id>` (scratch tenant via
  `KnowledgeBase`; DB-backed tests run in CI only).

## 2026-11-16 - TH-06 (injector part)

- `bomagent_eval.injection`: four error classes outside rule coverage (`BEYOND_RULES_KINDS`),
  `rule_coverage()` per class, `DetectionReport.false_alarms_by_rule`. Tests assert the rule pack
  detects none of the new classes (so B is not graded only on what its own rules check). The
  default mutation mix is unchanged so existing pilots stay comparable.
- Follow-up: `injection.kinds` in the experiment config and the coverage/false-alarm tables in the
  experiment report.

## 2026-11-16 - TH-06 (experiment wiring)

- `injection.kinds` in the experiment config (validated against the known kinds); the report shows
  rule coverage per error kind and false alarms per rule, and `detection_by_kind.csv` has a
  `rule_covered` column. Example: `injection: {kinds: [wrong_plausible_mpn, wrong_tolerance,
  voltage_derating, obsolete_part]}` measures what the rule pack cannot see.

## 2026-11-16 - TH-04

- `experiment_stats`: `holm_adjust`, `cluster_bootstrap_ci`, paired effect size d_z. The experiment
  report and `tables/paired.csv` carry the primary family (`line_f1`,
  `attempted_mpn_hallucination_rate`, `cost_eur`) with Holm-adjusted p, d_z and the cluster
  bootstrap interval as a sensitivity analysis.
- `docs/thesis/PREREJESTRACJA.md` (Polish, draft): hypotheses, unit of analysis, metric families,
  Holm, effect sizes, sensitivity analysis, rules. Owner: review and freeze it before the first
  real-model run.

## 2026-11-16 - TH-03 (tooling)

- `bomagent_eval.agreement`: per-field agreement and Cohen's kappa between two independent
  verifiers of a reference BOM, with the list of disagreements.
- `bomagent_eval.dataset`: `SOURCE.md` validation (URL, pinned commit, licence, date, two distinct
  verifiers for real designs), size strata, control vs real roles (`evals/fixtures/SOURCES.md`).
- Owner: choose and ingest at least six real open designs and do the two independent
  verifications; wiring a "never pool control and real" guard into the experiment config
  is a follow-up once real designs exist.

## 2026-11-16 - SEC-11

- `Settings.docs_enabled`: Swagger UI and `/openapi.json` are served only in local/test/dev; the
  contract is still published from the repository (`services/api/openapi.json`).

## 2026-11-16 - SEC-17

- `SECURITY.md` (private vulnerability reporting, scope, response times) and `.github/CODEOWNERS`
  (owner reviews everything, security-critical paths listed explicitly).
- Maintenance sweep deletes idempotency keys older than 24 h per tenant (`expired_keys` in the
  sweep totals).
- Regression test: parser error texts contain no paths, tracebacks or library internals.
- Owner: enable GitHub private vulnerability reporting, and branch protection with the
  `tenant isolation (blocking)` check.

## 2026-11-16 - batch of audit tasks merged (#38-#52)

- Merged: SEC-11 (#38), SEC-17 (#39), ARCH-07 (#40), DOC-04/OPS-03/OPS-07 (#42), UX-05/06/08 (#43),
  QA-02/03 (#44), OPS-05/06 (#45), SEC-09 (#46), ARCH-09/10 + DOC-01 as-built (#47), UX-02 backend
  (#48), TH-08/09 + capacitor "1M" fix (#49), OPS-08 lint + OPS-09 + QA-04/05 (#50), UX-04/07 (#51),
  ARCH-05 (#52).
- Open for the owner: #28 (Fly process groups, dashboards, alerts), #37 (gateway EU check at start,
  `deploy/*`), #55 (draft: downgrade round-trip test that exposes a broken `downgrade()` of the SSO
  revision). #41 (SEC-12) waits for CI.
- Found by the new tests: `normalize_value("1M", "capacitor")` produced "1 MF" (fixed);
  rolling back past the SSO revision fails on `tenancy.sso_domains` (needs a migration fix).

## 2026-11-17 - second batch merged (#41, #64-#67)

- Merged: SEC-12 (#41), OPS-04 (#64), SEC-10 report-only gates (#65), UX-03 lifecycle actions (#66),
  SEC-14 organisation export + sub-processor list (#67).
- Found while merging: the UX-05 slug-coverage test caught two untranslated export error slugs;
  the new version history made a Playwright selector ambiguous (fixed in the PR).
- Open for the owner: #28, #37 (`deploy/*`), #55 (draft; downgrade round-trip test that exposes the
  broken SSO downgrade). In progress: ARCH-06 (KB snapshot per run).

## 2026-11-17 - audit implementation: final report

- See the "Final report" at the top of `docs/audit/PROGRESS.md`. Merged: ARCH-06 (#69), ARCH-04
  (#70, partial). Open for the owner: #28, #37, #55 (draft), #71 (MFA), #72 (migrations bundle),
  #73 (SSO hardening). Not started: SEC-02.

## 2026-11-17 - audit follow-ups

- Merged: `runs.trace` size cap (#75, app level, `BOMAGENT_RUN_TRACE_MAX_BYTES`, default 256 KiB, 0 = off; full trace stays in object storage).
- Open for the owner: #76 ARCH-04 remainder (only the CodeQL false positive on `auth.py:296` blocks it).
